import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.config import settings
from app.models.availability import AvailabilityBlock
from app.models.booking import Booking, BookingState, PaymentMode
from app.services.booking_state import BookingStateMachine

settings.email_mode = "console"
settings.calendar_mode = "stub"


class BookingStateMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_conversation_starts_in_calendar_stub_mode(self) -> None:
        response = BookingStateMachine(self.db).handle_message("919999999999", "hi")

        self.assertIn("Standard Studio", response)
        self.assertIn("Premium Studio", response)

    def test_availability_is_rechecked_before_whatsapp_confirmation(self) -> None:
        booking_date = date.today() + timedelta(days=30)
        booking = Booking(
            phone_number="919999999999",
            state=BookingState.ASK_PAYMENT_MODE,
            space_id="standard_small",
            booking_date=booking_date.isoformat(),
            start_time="14:00",
            duration_hours=2,
            customer_name="Test Customer",
            customer_email="customer@example.com",
            purpose="Portrait shoot",
            terms_accepted="yes",
        )
        self.db.add_all(
            [
                booking,
                AvailabilityBlock(
                    space_id="standard_small",
                    booking_date=booking_date.isoformat(),
                    start_time="14:00",
                    duration_hours=1,
                    reason="Maintenance",
                ),
            ]
        )
        self.db.commit()

        response = BookingStateMachine(self.db).handle_message("919999999999", "continue")

        self.assertIn("blocked", response.lower())
        self.assertEqual(booking.state, BookingState.ASK_SCHEDULE)
        self.assertIsNone(booking.calendar_event_id)

    def test_terms_acceptance_uses_online_payment_without_asking_for_a_mode(self) -> None:
        booking_date = date.today() + timedelta(days=30)
        booking = Booking(
            phone_number="915555555555",
            state=BookingState.ASK_TERMS,
            space_id="standard_small",
            booking_date=booking_date.isoformat(),
            start_time="14:00",
            duration_hours=2,
            customer_name="Online Customer",
            customer_email="online@example.com",
            purpose="Fashion Shoot",
        )
        self.db.add(booking)
        self.db.commit()

        response = BookingStateMachine(self.db).handle_message("915555555555", "ACCEPT")

        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)
        self.assertEqual(booking.payment_mode, PaymentMode.PAY_NOW)
        self.assertIsNotNone(booking.payment_link)
        self.assertIn("Payment link:", response)
        self.assertNotIn("Choose payment mode", response)

    def test_whatsapp_accepts_half_hour_increments_above_two_hours(self) -> None:
        booking_date = date.today() + timedelta(days=30)
        booking = Booking(
            phone_number="918888888888",
            state=BookingState.ASK_SCHEDULE,
            space_id="standard_small",
        )
        self.db.add(booking)
        self.db.commit()

        response = BookingStateMachine(self.db).handle_message(
            "918888888888",
            f"{booking_date.isoformat()} 14:30 2.5",
        )

        self.assertIn("available", response.lower())
        self.assertEqual(booking.start_time, "14:30")
        self.assertEqual(booking.duration_hours, 2.5)
        self.assertEqual(booking.state, BookingState.ASK_NAME)

    def test_whatsapp_rejects_bookings_shorter_than_two_hours(self) -> None:
        booking = Booking(
            phone_number="916666666666",
            state=BookingState.ASK_SCHEDULE,
            space_id="standard_small",
        )
        self.db.add(booking)
        self.db.commit()

        response = BookingStateMachine(self.db).handle_message(
            "916666666666",
            f"{(date.today() + timedelta(days=30)).isoformat()} 14:30 1.5",
        )

        self.assertIn("minimum duration of 2 hours", response.lower())
        self.assertEqual(booking.state, BookingState.ASK_SCHEDULE)
        self.assertIsNone(booking.duration_hours)

    def test_whatsapp_uses_configured_purpose_options(self) -> None:
        booking = Booking(
            phone_number="917777777777",
            state=BookingState.ASK_PURPOSE,
            space_id="standard_small",
            customer_email="customer@example.com",
        )
        self.db.add(booking)
        self.db.commit()

        response = BookingStateMachine(self.db).handle_message("917777777777", "1")

        self.assertEqual(booking.purpose, "Fashion Shoot")
        self.assertEqual(booking.state, BookingState.ASK_TERMS)
        self.assertIn("accept", response.lower())


if __name__ == "__main__":
    unittest.main()
