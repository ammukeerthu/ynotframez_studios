from datetime import date, datetime, timedelta

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.booking import (
    AvailabilityRequest,
    AvailabilityResponse,
    BookingResponse,
    BookingLookupRequest,
    CustomerBookingStatusResponse,
    DayAvailabilityResponse,
    SpaceResponse,
    WebBookingCreate,
)
from app.models.booking import Booking, BookingState, PaymentMode
from app.models.payment import PaymentRecord, PaymentStatus
from app.services.payment_service import PaymentService
from app.services.booking_service import BookingApplicationService, BookingUnavailableError
from app.services.razorpay_service import RazorpayService
from app.services.spaces import get_space_by_id, get_space_by_slug, list_spaces

router = APIRouter(prefix="/api", tags=["Web bookings"])


def _webhook_booking(payload: dict, db: Session) -> Booking | None:
    event_payload = payload.get("payload", {})
    payment_link = event_payload.get("payment_link", {}).get("entity", {})
    payment = event_payload.get("payment", {}).get("entity", {})
    reference = payment_link.get("reference_id")
    notes = payment_link.get("notes") or payment.get("notes") or {}
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
    return None


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
        if booking.state != BookingState.CONFIRMED:
            booking.payment_mode = PaymentMode.PAY_NOW
            record.mode = PaymentMode.PAY_NOW
            service.confirm_paid_booking(booking, payment.get("id") or link.get("id"))
    elif event in {"payment.failed", "payment_link.expired", "payment_link.cancelled"}:
        service.record_payment_failure(booking)
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
    payment = payments.get(booking.id)
    payment_status = payment.status if payment else (
        PaymentStatus.VOID if booking.state == BookingState.CANCELLED else PaymentStatus.PENDING
    )
    start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
    space = get_space_by_id(booking.space_id, db, include_inactive=True)
    show_payment_link = (
        booking.state in {BookingState.PAYMENT_PENDING, BookingState.CONFIRMED}
        and payment_status == PaymentStatus.PENDING
        and booking.payment_mode == PaymentMode.PAY_NOW
    )
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
        payment_link=booking.payment_link if show_payment_link else None,
    )
