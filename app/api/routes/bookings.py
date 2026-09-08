from datetime import date, datetime, timedelta

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.booking import (
    AvailabilityRequest,
    AvailabilityResponse,
    BookingResponse,
    BookingLookupRequest,
    CustomerBookingStatusResponse,
    DayAvailabilityResponse,
    PaymentCheckoutRequest,
    RazorpayPaymentVerification,
    SpaceResponse,
    WebBookingCreate,
)
from app.models.booking import Booking, BookingState, PaymentMode
from app.models.payment import PaymentRecord, PaymentStatus
from app.services.payment_service import PaymentService
from app.services.booking_service import BookingApplicationService, BookingUnavailableError
from app.services.razorpay_service import RazorpayError, RazorpayService
from app.services.spaces import get_space_by_id, get_space_by_slug, list_spaces

router = APIRouter(prefix="/api", tags=["Web bookings"])


def _require_public_booking_enabled() -> None:
    if not settings.public_booking_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online booking is temporarily unavailable. Please contact the studio team.",
        )


def _webhook_booking(payload: dict, db: Session) -> Booking | None:
    event_payload = payload.get("payload", {})
    payment_link = event_payload.get("payment_link", {}).get("entity", {})
    order = event_payload.get("order", {}).get("entity", {})
    payment = event_payload.get("payment", {}).get("entity", {})
    reference = payment_link.get("reference_id") or order.get("receipt")
    notes = payment_link.get("notes") or order.get("notes") or payment.get("notes") or {}
    booking_id = notes.get("booking_id")
    if booking_id and str(booking_id).isdigit():
        return db.get(Booking, int(booking_id))
    if reference and str(reference).upper().startswith("YNF-"):
        numeric = str(reference).upper().removeprefix("YNF-")
        if numeric.isdigit():
            return db.get(Booking, int(numeric))
    link_id = payment_link.get("id")
    if link_id:
        record = db.scalar(select(PaymentRecord).where(PaymentRecord.provider_reference == link_id))
        return db.get(Booking, record.booking_id) if record else None
    order_id = order.get("id") or payment.get("order_id")
    if order_id:
        record = db.scalar(select(PaymentRecord).where(PaymentRecord.razorpay_order_id == order_id))
        return db.get(Booking, record.booking_id) if record else None
    return None


def _booking_from_reference(reference: str, db: Session) -> Booking | None:
    numeric = reference.strip().upper().removeprefix("YNF-")
    return db.get(Booking, int(numeric)) if numeric.isdigit() else None


def _validate_standard_payment(payment: dict, record: PaymentRecord, expected_order_id: str) -> None:
    if payment.get("id") is None or payment.get("order_id") != expected_order_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay payment order mismatch.")
    if payment.get("currency") != "INR" or int(payment.get("amount", 0)) != record.amount * 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay payment amount mismatch.")


def _razorpay_method(payment: dict) -> str | None:
    method = str(payment.get("method") or "").strip().lower()
    return method[:40] or None


def _customer_payment_method(booking: Booking, record: PaymentRecord | None) -> str:
    if record and record.razorpay_method:
        return record.razorpay_method
    if booking.payment_mode == PaymentMode.PAY_AT_STUDIO:
        return "pay_at_studio"
    if record and record.status == PaymentStatus.PENDING:
        return "pending"
    if record and record.status in {PaymentStatus.PAID, PaymentStatus.REFUND_DUE, PaymentStatus.REFUNDED}:
        return "recorded_by_studio" if not record.razorpay_payment_id else "online"
    return "online"


def _backfill_razorpay_method(service: BookingApplicationService, record: PaymentRecord | None) -> bool:
    """Hydrate the method for payments completed before this field was introduced."""
    if (
        record is None
        or record.razorpay_method
        or not record.razorpay_payment_id
        or not record.razorpay_order_id
        or settings.razorpay_mode.strip().lower() != "api"
    ):
        return False
    try:
        payment = service.razorpay.fetch_payment(record.razorpay_payment_id)
    except RazorpayError:
        return False
    if (
        payment.get("id") != record.razorpay_payment_id
        or payment.get("order_id") != record.razorpay_order_id
        or payment.get("currency") != "INR"
        or int(payment.get("amount", 0)) != record.amount * 100
    ):
        return False
    method = _razorpay_method(payment)
    if not method:
        return False
    record.razorpay_method = method
    return True


@router.get("/spaces", response_model=list[SpaceResponse])
def public_spaces(db: Session = Depends(get_db)) -> list[SpaceResponse]:
    return [SpaceResponse(**vars(space)) for space in list_spaces(db)]


@router.get("/spaces/{slug}", response_model=SpaceResponse)
def get_space(slug: str, db: Session = Depends(get_db)) -> SpaceResponse:
    space = get_space_by_slug(slug, db)
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")
    return SpaceResponse(**vars(space))


@router.post("/availability", response_model=AvailabilityResponse)
def check_availability(
    payload: AvailabilityRequest,
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    available, message = BookingApplicationService(db).check_availability(payload)
    return AvailabilityResponse(available=available, message=message)


@router.get("/availability/day", response_model=DayAvailabilityResponse)
def get_day_availability(
    space_id: str = Query(...),
    booking_date: date = Query(...),
    db: Session = Depends(get_db),
) -> DayAvailabilityResponse:
    if get_space_by_id(space_id, db) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio space not found.")
    return BookingApplicationService(db).get_day_availability(space_id, booking_date)


@router.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: WebBookingCreate,
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_public_booking_enabled()
    try:
        return BookingApplicationService(db).create_booking(payload)
    except BookingUnavailableError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except Exception:
        db.rollback()
        raise


@router.post("/bookings/checkout", response_model=BookingResponse)
def retry_booking_checkout(
    payload: PaymentCheckoutRequest,
    db: Session = Depends(get_db),
) -> BookingResponse:
    booking = _booking_from_reference(payload.reference, db)
    if (
        booking is None
        or not booking.customer_email
        or booking.customer_email.casefold() != str(payload.customer_email).casefold()
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No booking matched that reference and email address.",
        )
    service = BookingApplicationService(db)
    if service.expire_payment_hold(booking):
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The temporary payment hold has expired. Please create a new booking.",
        )
    if booking.state != BookingState.PAYMENT_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This booking is not awaiting payment.")
    if booking.payment_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This booking already has a hosted payment link. Use that link to complete payment.",
        )
    checkout = service.prepare_standard_checkout(booking)
    db.commit()
    if checkout is None or not checkout.key_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online checkout is temporarily unavailable. Please try again shortly.",
        )
    return service.booking_response(booking, checkout=checkout)


@router.post("/payments/razorpay/verify", response_model=BookingResponse)
def verify_razorpay_payment(
    payload: RazorpayPaymentVerification,
    db: Session = Depends(get_db),
) -> BookingResponse:
    booking = _booking_from_reference(payload.reference, db)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    service = BookingApplicationService(db)
    record = service.payments.get(booking.id)
    stored_order_id = record.razorpay_order_id if record else None
    if not stored_order_id or stored_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay order mismatch.")
    if not RazorpayService.verify_payment_signature(
        stored_order_id,
        payload.razorpay_payment_id,
        payload.razorpay_signature,
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Razorpay signature.")
    try:
        payment = service.razorpay.fetch_payment(payload.razorpay_payment_id)
    except RazorpayError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment was received but its status could not be verified yet.",
        ) from error
    _validate_standard_payment(payment, record, stored_order_id)
    method = _razorpay_method(payment)
    service.expire_payment_hold(booking)
    if payment.get("status") != "captured":
        record.razorpay_payment_id = payload.razorpay_payment_id
        record.razorpay_method = method
        db.commit()
        return service.booking_response(booking)
    if booking.state not in {BookingState.PAYMENT_PENDING, BookingState.CONFIRMED}:
        service.record_unreservable_payment(
            booking,
            stored_order_id,
            payload.razorpay_payment_id,
            method,
        )
    else:
        try:
            service.confirm_paid_booking(
                booking,
                payload.razorpay_payment_id,
                razorpay_order_id=stored_order_id,
                razorpay_payment_id=payload.razorpay_payment_id,
                razorpay_method=method,
            )
        except BookingUnavailableError:
            service.record_unreservable_payment(
                booking,
                stored_order_id,
                payload.razorpay_payment_id,
                method,
            )
    db.commit()
    return service.booking_response(booking)


@router.post("/payments/razorpay/webhook", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    raw_payload = await request.body()
    if not RazorpayService.verify_webhook_signature(raw_payload, x_razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Razorpay signature.")
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload.") from error

    event = payload.get("event", "")
    booking = _webhook_booking(payload, db)
    if booking is None:
        return {"ok": True}
    service = BookingApplicationService(db)
    service.expire_payment_hold(booking)
    if event == "payment_link.paid":
        link = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
        payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
        record = service.payments.get(booking.id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment record not found.")
        if link.get("status") != "paid" or link.get("currency") not in {None, "INR"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay link is not fully paid.")
        if int(link.get("amount_paid", 0)) != record.amount * 100:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay amount does not match.")
        if booking.state not in {BookingState.PAYMENT_PENDING, BookingState.CONFIRMED}:
            service.record_unreservable_payment(
                booking,
                None,
                payment.get("id") or link.get("id"),
                _razorpay_method(payment),
            )
        elif booking.state != BookingState.CONFIRMED:
            booking.payment_mode = PaymentMode.PAY_NOW
            record.mode = PaymentMode.PAY_NOW
            service.confirm_paid_booking(
                booking,
                payment.get("id") or link.get("id"),
                razorpay_payment_id=payment.get("id"),
                razorpay_method=_razorpay_method(payment),
            )
    elif event in {"payment.captured", "order.paid"}:
        event_payload = payload.get("payload", {})
        order = event_payload.get("order", {}).get("entity", {})
        payment = event_payload.get("payment", {}).get("entity", {})
        record = service.payments.get(booking.id)
        order_id = order.get("id") or payment.get("order_id")
        payment_id = payment.get("id")
        if record is None or not order_id or not payment_id or record.razorpay_order_id != order_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay order mismatch.")
        _validate_standard_payment(payment, record, order_id)
        method = _razorpay_method(payment)
        if payment.get("status") != "captured" and order.get("status") != "paid":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay payment is not captured.")
        if booking.state not in {BookingState.PAYMENT_PENDING, BookingState.CONFIRMED}:
            service.record_unreservable_payment(booking, order_id, payment_id, method)
        else:
            try:
                service.confirm_paid_booking(
                    booking,
                    payment_id,
                    razorpay_order_id=order_id,
                    razorpay_payment_id=payment_id,
                    razorpay_method=method,
                )
            except BookingUnavailableError:
                service.record_unreservable_payment(booking, order_id, payment_id, method)
    elif event == "payment.failed":
        failed_payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
        failed_order_id = failed_payment.get("order_id")
        failed_record = service.payments.get(booking.id)
        if (
            failed_record is None
            or not failed_order_id
            or failed_record.razorpay_order_id != failed_order_id
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razorpay order mismatch.")
        service.record_checkout_attempt_failure(booking, failed_payment.get("id"))
    elif event in {"payment_link.expired", "payment_link.cancelled"}:
        service.expire_payment_hold(booking, force=True)
    db.commit()
    return {"ok": True}


@router.post("/bookings/lookup", response_model=CustomerBookingStatusResponse)
def lookup_booking(
    payload: BookingLookupRequest,
    db: Session = Depends(get_db),
) -> CustomerBookingStatusResponse:
    booking_id = int(payload.reference.removeprefix("YNF-"))
    booking = db.get(Booking, booking_id)
    if booking is None or not booking.customer_email or booking.customer_email.casefold() != str(payload.customer_email).casefold():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No booking matched that reference and email address.",
        )
    if not booking.booking_date or not booking.start_time or not booking.duration_hours:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That booking is not yet complete.")

    payments = PaymentService(db)
    service = BookingApplicationService(db)
    hold_expired = service.expire_payment_hold(booking)
    payment = payments.get(booking.id)
    if hold_expired or _backfill_razorpay_method(service, payment):
        db.commit()
    payment_status = payment.status if payment else (
        PaymentStatus.VOID
        if booking.state in {BookingState.CANCELLED, BookingState.EXPIRED}
        else PaymentStatus.PENDING
    )
    start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
    space = get_space_by_id(booking.space_id, db, include_inactive=True)
    show_payment_action = (
        booking.state in {BookingState.PAYMENT_PENDING, BookingState.CONFIRMED}
        and payment_status == PaymentStatus.PENDING
        and booking.payment_mode == PaymentMode.PAY_NOW
    )
    checkout = (
        service.prepare_standard_checkout(booking)
        if show_payment_action and not booking.payment_link and service.payment_hold_active(booking)
        else None
    )
    if checkout is not None:
        db.commit()
    return CustomerBookingStatusResponse(
        reference=f"YNF-{booking.id:06d}",
        booking_status=booking.state.value,
        payment_status=payment_status.value,
        space_name=space.name if space else booking.space_id or "Studio Space",
        booking_date=booking.booking_date,
        start_time=booking.start_time,
        end_time=(start + timedelta(hours=booking.duration_hours)).strftime("%H:%M"),
        duration_hours=booking.duration_hours,
        total_amount=payment.amount if payment else payments.amount_for(booking),
        customer_name=booking.customer_name or "Customer",
        customer_email=booking.customer_email,
        payment_mode=booking.payment_mode.value if booking.payment_mode else PaymentMode.PAY_AT_STUDIO.value,
        payment_method=_customer_payment_method(booking, payment),
        payment_link=booking.payment_link if show_payment_action else None,
        checkout=checkout,
    )
