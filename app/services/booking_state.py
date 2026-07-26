from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingState, PaymentMode
from app.services.calendar_service import GoogleCalendarService
from app.services.email_service import EmailService
from app.services.razorpay_service import RazorpayService
from app.services.spaces import get_space_by_id, get_space_by_input, list_spaces_message


class BookingStateMachine:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.calendar = GoogleCalendarService()
        self.razorpay = RazorpayService()
        self.email = EmailService()

    def handle_message(self, phone_number: str, message: str) -> str:
        text = message.strip()
        normalized = text.lower()
        booking = self._get_or_create_active_booking(phone_number)

        if normalized in {"restart", "start", "hi", "hello", "book"}:
            if self._is_empty_booking(booking):
                booking.state = BookingState.SELECT_SPACE
            else:
                booking = self._create_booking(phone_number)
            self.db.commit()
            return list_spaces_message()

        handlers = {
            BookingState.SELECT_SPACE: self._handle_select_space,
            BookingState.SHOW_DETAILS: self._handle_show_details,
            BookingState.SHOW_RULES: self._handle_show_rules,
            BookingState.ASK_SCHEDULE: self._handle_schedule,
            BookingState.ASK_NAME: self._handle_name,
            BookingState.ASK_EMAIL: self._handle_email,
            BookingState.ASK_PURPOSE: self._handle_purpose,
            BookingState.ASK_TERMS: self._handle_terms,
            BookingState.ASK_PAYMENT_MODE: self._handle_payment_mode,
            BookingState.PAYMENT_PENDING: self._handle_payment_pending,
            BookingState.CONFIRMED: self._handle_confirmed,
        }
        handler = handlers.get(booking.state, self._handle_select_space)
        reply = handler(booking, text)
        self.db.commit()
        return reply

    def _get_or_create_active_booking(self, phone_number: str) -> Booking:
        stmt = (
            select(Booking)
            .where(Booking.phone_number == phone_number)
            .where(Booking.state.notin_([BookingState.CANCELLED, BookingState.CONFIRMED]))
            .order_by(Booking.created_at.desc())
        )
        booking = self.db.scalars(stmt).first()
        if booking:
            return booking

        return self._create_booking(phone_number)

    def _create_booking(self, phone_number: str) -> Booking:
        booking = Booking(phone_number=phone_number, state=BookingState.SELECT_SPACE)
        self.db.add(booking)
        self.db.flush()
        return booking

    def _handle_select_space(self, booking: Booking, text: str) -> str:
        space = get_space_by_input(text)
        if not space:
            return list_spaces_message()

        booking.space_id = space.id
        booking.state = BookingState.SHOW_DETAILS
        return f"{space.brochure}\n\nReply YES to see rules."

    def _handle_show_details(self, booking: Booking, text: str) -> str:
        if text.lower() not in {"yes", "y"}:
            return "Please reply YES to continue to the studio rules."

        space = get_space_by_id(booking.space_id)
        booking.state = BookingState.SHOW_RULES
        return f"{space.rules if space else 'Please follow all studio rules.'}\n\nReply YES to choose date and time."

    def _handle_show_rules(self, booking: Booking, text: str) -> str:
        if text.lower() not in {"yes", "y"}:
            return "Please reply YES after reading the rules."

        booking.state = BookingState.ASK_SCHEDULE
        return "Please send booking details as: YYYY-MM-DD HH:MM duration_hours\nExample: 2026-06-15 14:00 2"

    def _handle_schedule(self, booking: Booking, text: str) -> str:
        try:
            booking_date, start_time, duration = text.split(maxsplit=2)
            duration_hours = int(duration)
            datetime.strptime(f"{booking_date} {start_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return "Please use this format: YYYY-MM-DD HH:MM duration_hours\nExample: 2026-06-15 14:00 2"

        if duration_hours <= 0:
            return "Duration must be at least 1 hour. Please send the date, time, and duration again."

        booking.booking_date = booking_date
        booking.start_time = start_time
        booking.duration_hours = duration_hours

        if not self.calendar.is_available(booking):
            return "Sorry, that slot is not available. Please choose a time between 09:00 and 20:00."

        booking.state = BookingState.ASK_NAME
        return "Great, that slot is available. Please share your full name."

    def _handle_name(self, booking: Booking, text: str) -> str:
        if len(text) < 2:
            return "Please share your full name."

        booking.customer_name = text
        booking.state = BookingState.ASK_EMAIL
        return "Please share your email address for the confirmation."

    def _handle_email(self, booking: Booking, text: str) -> str:
        if "@" not in text or "." not in text:
            return "Please share a valid email address."

        booking.customer_email = text
        booking.state = BookingState.ASK_PURPOSE
        return "What is the purpose of your shoot?"

    def _handle_purpose(self, booking: Booking, text: str) -> str:
        if len(text) < 3:
            return "Please describe the purpose of your shoot."

        booking.purpose = text
        booking.state = BookingState.ASK_TERMS
        return "Do you accept the studio terms and rules? Reply ACCEPT to continue."

    def _handle_terms(self, booking: Booking, text: str) -> str:
        if text.lower() != "accept":
            return "Please reply ACCEPT to confirm that you accept the studio terms and rules."

        booking.terms_accepted = "yes"
        booking.state = BookingState.ASK_PAYMENT_MODE
        return "Choose payment mode:\n1. Pay Now\n2. Pay at Studio\n\nReply with 1 or 2."

    def _handle_payment_mode(self, booking: Booking, text: str) -> str:
        normalized = text.strip().lower()
        if normalized in {"1", "pay now", "pay_now"}:
            booking.payment_mode = PaymentMode.PAY_NOW
            booking.payment_link = self.razorpay.create_payment_link(booking)
            booking.state = BookingState.PAYMENT_PENDING
            self._confirm_booking(booking)
            return self._confirmation_message(booking)

        if normalized in {"2", "pay at studio", "pay_at_studio"}:
            booking.payment_mode = PaymentMode.PAY_AT_STUDIO
            self._confirm_booking(booking)
            return self._confirmation_message(booking)

        return "Please choose payment mode:\n1. Pay Now\n2. Pay at Studio"

    def _handle_payment_pending(self, booking: Booking, text: str) -> str:
        return self._confirmation_message(booking)

    def _handle_confirmed(self, booking: Booking, text: str) -> str:
        return "Your booking is already confirmed. Reply RESTART to make a new booking."

    def _confirm_booking(self, booking: Booking) -> None:
        booking.calendar_event_id = self.calendar.create_event(booking)
        booking.state = BookingState.CONFIRMED
        self.email.send_booking_confirmation(booking)

    def _confirmation_message(self, booking: Booking) -> str:
        space = get_space_by_id(booking.space_id)
        payment_note = (
            f"\nPayment link: {booking.payment_link}" if booking.payment_mode == PaymentMode.PAY_NOW else "\nPayment: Pay at Studio"
        )
        return (
            "Booking confirmed.\n\n"
            f"Space: {space.name if space else booking.space_id}\n"
            f"Date: {booking.booking_date}\n"
            f"Time: {booking.start_time}\n"
            f"Duration: {booking.duration_hours} hour(s)\n"
            f"Name: {booking.customer_name}\n"
            f"Email: {booking.customer_email}"
            f"{payment_note}\n\n"
            "A confirmation email has been sent."
        )

    def _is_empty_booking(self, booking: Booking) -> bool:
        return (
            booking.state == BookingState.SELECT_SPACE
            and booking.space_id is None
            and booking.booking_date is None
            and booking.customer_name is None
        )
