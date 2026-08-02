from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking, BookingState, PaymentMode
from app.schemas.booking import (
    AvailabilityRequest,
    AvailabilitySlot,
    BookingResponse,
    DayAvailabilityResponse,
    WebBookingCreate,
)
from app.services.calendar_service import GoogleCalendarService
from app.services.availability_service import overlapping_block, overlapping_booking
from app.services.email_service import EmailService
from app.services.payment_service import PaymentService
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

    def check_availability(
        self,
        request: AvailabilityRequest,
        exclude_booking_id: int | None = None,
        ignore_calendar_event_id: str | None = None,
        enforce_duration_limits: bool = True,
    ) -> tuple[bool, str]:
        space = get_space_by_id(request.space_id, self.db)
        if not space:
            return False, "Please select a valid studio space."
        if enforce_duration_limits and not space.min_duration_hours <= request.duration_hours <= space.max_duration_hours:
            return False, (
                f"Bookings for {space.name} must be between "
                f"{space.min_duration_hours:g} and {space.max_duration_hours:g} hours."
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
        if not self.calendar.is_available(candidate, ignore_event_id=ignore_calendar_event_id):
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
            available, message = self.check_availability(request, enforce_duration_limits=False)
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
            terms_accepted="yes",
            payment_mode=PaymentMode(request.payment_mode),
        )
        self.db.add(booking)
        self.db.flush()

        if booking.payment_mode == PaymentMode.PAY_NOW:
            booking.payment_link = self.razorpay.create_payment_link(booking)

        self.payments.ensure(booking)
        booking.calendar_event_id = self.calendar.create_event(booking)
        booking.state = BookingState.CONFIRMED
        self.email.send_booking_confirmation(booking)
        self.db.commit()
        self.db.refresh(booking)

        return BookingResponse(
            id=booking.id,
            reference=f"YNF-{booking.id:06d}",
            status=booking.state.value,
            space_name=space.name,
            booking_date=booking.booking_date,
            start_time=booking.start_time,
            end_time=(
                datetime.combine(request.booking_date, request.start_time)
                + timedelta(hours=booking.duration_hours)
            ).strftime("%H:%M"),
            duration_hours=booking.duration_hours,
            total_amount=int(round(space.hourly_rate * booking.duration_hours)),
            customer_name=booking.customer_name,
            customer_email=booking.customer_email,
            payment_mode=booking.payment_mode.value,
            payment_link=booking.payment_link,
            calendar_event_id=booking.calendar_event_id,
        )
