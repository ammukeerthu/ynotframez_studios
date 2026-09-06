from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.booking_rules import CURRENT_TERMS_VERSION, MINIMUM_BOOKING_DURATION_HOURS
from app.core.config import settings
from app.models.booking import Booking, BookingState, PaymentMode
from app.schemas.booking import (
    AvailabilityRequest,
    AvailabilitySlot,
    BookingResponse,
    DayAvailabilityResponse,
    RazorpayCheckoutResponse,
    WebBookingCreate,
)
from app.services.calendar_service import GoogleCalendarService
from app.services.availability_service import overlapping_block, overlapping_booking
from app.services.email_service import EmailService
from app.services.payment_service import PaymentService
from app.services.notification_service import notify_new_booking, notify_payment_issue
from app.services.razorpay_service import RazorpayService
from app.services.spaces import get_space_by_id


class BookingUnavailableError(ValueError):
    pass


class BookingApplicationService:
    """Shared application service for web booking availability and confirmation."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.calendar = GoogleCalendarService(db)
        self.razorpay = RazorpayService(db)
        self.email = EmailService(db)
        self.payments = PaymentService(db)

    def prepare_payment_link(self, booking: Booking) -> bool:
        """Create a hosted link for WhatsApp while leaving the booking unconfirmed."""
        booking.payment_mode = PaymentMode.PAY_NOW
        booking.payment_link = None
        payment = self.payments.ensure(booking)
        payment.mode = PaymentMode.PAY_NOW
        try:
            payment_link = self.razorpay.create_payment_link(booking)
            if not payment_link.url:
                raise ValueError("The payment provider returned an empty payment link.")
        except Exception as error:
            booking.payment_mode = PaymentMode.PAY_AT_STUDIO
            payment.mode = PaymentMode.PAY_AT_STUDIO
            print(
                "Payment link creation failed; booking remains pending for studio follow-up:",
                {"booking_id": booking.id, "error": f"{type(error).__name__}: {error}"},
            )
            self.email.send_payment_failed(booking)
            return False
        booking.payment_link = payment_link.url
        payment.provider_reference = payment_link.id
        return True

    def prepare_standard_checkout(
        self,
        booking: Booking,
        *,
        notify_failure: bool = False,
    ) -> RazorpayCheckoutResponse | None:
        """Create or reuse the server-owned order for the website checkout modal."""
        booking.payment_mode = PaymentMode.PAY_NOW
        booking.payment_link = None
        payment = self.payments.ensure(booking)
        payment.mode = PaymentMode.PAY_NOW
        if payment.razorpay_order_id and not (
            settings.razorpay_mode.strip().lower() == "api"
            and payment.razorpay_order_id.startswith("order_stub_")
        ):
            return RazorpayCheckoutResponse(
                key_id=settings.razorpay_key_id.strip(),
                order_id=payment.razorpay_order_id,
                amount=payment.amount * 100,
                currency="INR",
            )
        try:
            order = self.razorpay.create_order(booking, payment.amount)
        except Exception as error:
            print(
                "Razorpay order creation failed; booking remains payment pending:",
                {"booking_id": booking.id, "error": f"{type(error).__name__}: {error}"},
            )
            if notify_failure:
                self.email.send_payment_failed(booking)
            return None
        payment.razorpay_order_id = order.id
        return RazorpayCheckoutResponse(
            key_id=order.key_id,
            order_id=order.id,
            amount=order.amount,
            currency=order.currency,
        )

    # Backward-compatible name for callers that still use hosted Payment Links.
    prepare_online_payment = prepare_payment_link

    def confirm_paid_booking(
        self,
        booking: Booking,
        provider_reference: str | None = None,
        *,
        razorpay_order_id: str | None = None,
        razorpay_payment_id: str | None = None,
        razorpay_method: str | None = None,
    ) -> None:
        """Reserve the studio only after a verified or owner-recorded payment."""
        if booking.state == BookingState.CONFIRMED:
            payment = self.payments.get(booking.id)
            if payment is not None:
                if razorpay_order_id:
                    payment.razorpay_order_id = razorpay_order_id
                if razorpay_payment_id:
                    payment.razorpay_payment_id = razorpay_payment_id
                if razorpay_method:
                    payment.razorpay_method = razorpay_method.strip().lower()
            return
        if booking.state != BookingState.PAYMENT_PENDING:
            raise ValueError("Only a payment-pending booking can be confirmed.")
        available, message = self.check_availability(
            AvailabilityRequest(
                space_id=booking.space_id or "",
                booking_date=date.fromisoformat(booking.booking_date or ""),
                start_time=time.fromisoformat(booking.start_time or ""),
                duration_hours=booking.duration_hours or 0,
            ),
            exclude_booking_id=booking.id,
        )
        if not available:
            raise BookingUnavailableError(message)
        payment = self.payments.get(booking.id)
        if payment is None or payment.status.value != "pending":
            raise ValueError("The booking does not have a pending payment.")
        self.payments.mark_paid(
            booking,
            provider_reference,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_method=razorpay_method,
        )
        booking.calendar_event_id = self.calendar.create_event(booking)
        booking.state = BookingState.CONFIRMED
        notify_new_booking(self.db, booking)
        self.email.send_booking_confirmation(booking)

    def record_payment_failure(self, booking: Booking) -> None:
        if booking.state != BookingState.PAYMENT_PENDING:
            return
        first_failure = booking.payment_mode != PaymentMode.PAY_AT_STUDIO
        booking.payment_mode = PaymentMode.PAY_AT_STUDIO
        booking.payment_link = None
        payment = self.payments.ensure(booking)
        payment.mode = PaymentMode.PAY_AT_STUDIO
        if first_failure:
            self.email.send_payment_failed(booking)

    def record_checkout_attempt_failure(
        self,
        booking: Booking,
        provider_reference: str | None = None,
    ) -> None:
        """Keep the order retryable while its temporary booking hold is active."""
        if booking.state == BookingState.PAYMENT_PENDING:
            payment = self.payments.ensure(booking)
            payment.mode = PaymentMode.PAY_NOW
            reference = provider_reference.strip() if provider_reference else None
            if not reference or payment.provider_reference != reference:
                payment.provider_reference = reference
                self.email.send_payment_failed(booking)

    def record_unreservable_payment(
        self,
        booking: Booking,
        order_id: str,
        payment_id: str,
        razorpay_method: str | None = None,
    ) -> None:
        """Release a stale hold and alert the owner when captured money needs review."""
        booking.state = BookingState.CANCELLED
        booking.payment_link = None
        self.payments.mark_refund_due(
            booking,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_method=razorpay_method,
        )
        notify_payment_issue(self.db, booking)

    def payment_hold_active(self, booking: Booking) -> bool:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            minutes=settings.razorpay_payment_hold_minutes
        )
        return booking.created_at >= cutoff

    def check_availability(
        self,
        request: AvailabilityRequest,
        exclude_booking_id: int | None = None,
        ignore_calendar_event_id: str | None = None,
        enforce_duration_limits: bool = True,
        calendar_events: list[dict] | None = None,
    ) -> tuple[bool, str]:
        space = get_space_by_id(request.space_id, self.db)
        if not space:
            return False, "Please select a valid studio space."
        minimum_duration = max(space.min_duration_hours, MINIMUM_BOOKING_DURATION_HOURS)
        if enforce_duration_limits and not minimum_duration <= request.duration_hours <= space.max_duration_hours:
            return False, (
                f"Bookings for {space.name} must be between "
                f"{minimum_duration:g} and {space.max_duration_hours:g} hours."
            )

        requested_start = datetime.combine(request.booking_date, request.start_time)
        requested_end = requested_start + timedelta(hours=request.duration_hours)
        studio_now = datetime.now(ZoneInfo(settings.studio_timezone)).replace(tzinfo=None)
        if requested_start <= studio_now:
            return False, "Please choose a future date and time."
        if (request.booking_date - studio_now.date()).days > settings.future_booking_days:
            return False, f"Bookings can be made up to {settings.future_booking_days} days in advance."

        if overlapping_booking(
            self.db,
            request.space_id,
            request.booking_date,
            requested_start,
            requested_end,
            exclude_booking_id,
        ):
            return False, "That slot has just been booked. Please choose another time."

        if overlapping_block(
            self.db,
            request.space_id,
            request.booking_date,
            requested_start,
            requested_end,
        ):
            return False, "That time has been blocked by the studio. Please choose another slot."

        candidate = Booking(
            phone_number="web-availability-check",
            space_id=request.space_id,
            booking_date=request.booking_date.isoformat(),
            start_time=request.start_time.strftime("%H:%M"),
            duration_hours=request.duration_hours,
        )
        if not self.calendar.is_available(
            candidate,
            ignore_event_id=ignore_calendar_event_id,
            events=calendar_events,
        ):
            return False, (
                "That slot is unavailable. Studio hours are "
                f"{space.opening_time} to {space.closing_time}."
            )

        return True, "Your selected slot is available."

    def get_day_availability(self, space_id: str, booking_date: date) -> DayAvailabilityResponse:
        space = get_space_by_id(space_id, self.db, include_inactive=True)
        if space is None:
            raise ValueError("Studio space not found.")
        slots: list[AvailabilitySlot] = []
        studio_now = datetime.now(ZoneInfo(settings.studio_timezone)).replace(tzinfo=None)
        day_start = datetime.combine(booking_date, time.fromisoformat(space.opening_time))
        day_end = datetime.combine(booking_date, time.fromisoformat(space.closing_time))
        within_booking_window = 0 <= (booking_date - studio_now.date()).days <= settings.future_booking_days
        calendar_events = (
            self.calendar.events_for_day(
                space_id,
                booking_date,
                space.opening_time,
                space.closing_time,
            )
            if day_end > studio_now and within_booking_window
            else []
        )
        slot_start = day_start
        while slot_start < day_end:
            slot_end = slot_start + timedelta(minutes=30)
            start = slot_start.time()
            end = slot_end.time()
            request = AvailabilityRequest(
                space_id=space_id,
                booking_date=booking_date,
                start_time=start,
                duration_hours=0.5,
            )
            available, message = self.check_availability(
                request,
                enforce_duration_limits=False,
                calendar_events=calendar_events,
            )
            slot_start = datetime.combine(booking_date, start)
            if available:
                status = "available"
            elif slot_start <= studio_now:
                status = "past"
            elif "booked" in message.lower():
                status = "booked"
            elif "blocked" in message.lower():
                status = "blocked"
            else:
                status = "unavailable"
            slots.append(
                AvailabilitySlot(
                    start_time=start.strftime("%H:%M"),
                    end_time=end.strftime("%H:%M"),
                    status=status,
                )
            )
            slot_start = slot_end

        return DayAvailabilityResponse(
            space_id=space_id,
            booking_date=booking_date.isoformat(),
            opening_time=space.opening_time,
            closing_time=space.closing_time,
            slots=slots,
        )

    def create_booking(self, request: WebBookingCreate) -> BookingResponse:
        if not request.terms_accepted:
            raise ValueError("Studio terms must be accepted before booking.")

        available, message = self.check_availability(request)
        if not available:
            raise BookingUnavailableError(message)

        space = get_space_by_id(request.space_id, self.db)
        if space is None:
            raise ValueError("Invalid studio space.")
        selected_purpose = next(
            (purpose for purpose in space.booking_purposes if purpose.casefold() == request.purpose.strip().casefold()),
            None,
        )
        if selected_purpose is None:
            raise ValueError("Please choose a valid booking purpose for this studio.")

        booking = Booking(
            phone_number=request.phone_number.strip(),
            state=BookingState.ASK_PAYMENT_MODE,
            space_id=request.space_id,
            booking_date=request.booking_date.isoformat(),
            start_time=request.start_time.strftime("%H:%M"),
            duration_hours=request.duration_hours,
            customer_name=request.customer_name.strip(),
            customer_email=str(request.customer_email),
            purpose=selected_purpose,
            terms_accepted=CURRENT_TERMS_VERSION,
            payment_mode=PaymentMode(request.payment_mode),
        )
        self.db.add(booking)
        self.db.flush()

        self.payments.ensure(booking)
        checkout = self.prepare_standard_checkout(booking, notify_failure=True)
        booking.state = BookingState.PAYMENT_PENDING
        self.db.commit()
        self.db.refresh(booking)

        return self.booking_response(booking, checkout=checkout)

    def booking_response(
        self,
        booking: Booking,
        *,
        checkout: RazorpayCheckoutResponse | None = None,
    ) -> BookingResponse:
        space = get_space_by_id(booking.space_id or "", self.db, include_inactive=True)
        payment = self.payments.get(booking.id)
        booking_date = date.fromisoformat(booking.booking_date or "")
        start_time = time.fromisoformat(booking.start_time or "")
        return BookingResponse(
            id=booking.id,
            reference=f"YNF-{booking.id:06d}",
            status=booking.state.value,
            space_name=space.name if space else "Studio Space",
            booking_date=booking.booking_date or "",
            start_time=booking.start_time or "",
            end_time=(
                datetime.combine(booking_date, start_time)
                + timedelta(hours=booking.duration_hours or 0)
            ).strftime("%H:%M"),
            duration_hours=booking.duration_hours or 0,
            total_amount=payment.amount if payment else 0,
            customer_name=booking.customer_name or "Customer",
            customer_email=booking.customer_email or "unknown@example.com",
            phone_number=booking.phone_number,
            payment_mode=(booking.payment_mode or PaymentMode.PAY_NOW).value,
            payment_link=booking.payment_link,
            checkout=checkout,
            calendar_event_id=booking.calendar_event_id,
        )
