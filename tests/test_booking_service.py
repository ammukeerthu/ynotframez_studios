import unittest
from datetime import date, time, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.config import settings
from app.models.availability import AvailabilityBlock
from app.schemas.booking import AvailabilityRequest, WebBookingCreate
from app.services.booking_service import BookingApplicationService, BookingUnavailableError
from app.services.payment_service import PaymentService

settings.email_mode = "console"


class BookingApplicationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.service = BookingApplicationService(self.db)
        self.future_date = date.today() + timedelta(days=30)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def availability(self, **overrides) -> AvailabilityRequest:
        values = {
            "space_id": "standard_small",
            "booking_date": self.future_date,
            "start_time": time(11, 0),
            "duration_hours": 2,
        }
        values.update(overrides)
        return AvailabilityRequest(**values)

    def booking(self, **overrides) -> WebBookingCreate:
        values = {
            **self.availability().model_dump(),
            "customer_name": "Test Customer",
            "customer_email": "customer@example.com",
            "phone_number": "+919999999999",
            "purpose": "Fashion Shoot",
            "terms_accepted": True,
            "payment_mode": "pay_now",
        }
        values.update(overrides)
        return WebBookingCreate(**values)

    def test_stub_calendar_enforces_business_hours(self) -> None:
        available, _ = self.service.check_availability(self.availability())
        outside_hours, _ = self.service.check_availability(
            self.availability(start_time=time(19, 0), duration_hours=2)
        )

        self.assertTrue(available)
        self.assertFalse(outside_hours)

    def test_day_availability_returns_half_hour_slot_states(self) -> None:
        before_booking = self.service.get_day_availability("standard_small", self.future_date)
        self.service.create_booking(self.booking())
        after_booking = self.service.get_day_availability("standard_small", self.future_date)

        self.assertEqual(before_booking.opening_time, "09:00")
        self.assertEqual(before_booking.closing_time, "20:00")
        self.assertEqual(len(before_booking.slots), 22)
        states = {slot.start_time: slot.status for slot in after_booking.slots}
        self.assertEqual(states["11:00"], "booked")
        self.assertEqual(states["11:30"], "booked")
        self.assertEqual(states["12:00"], "booked")
        self.assertEqual(states["12:30"], "booked")
        self.assertEqual(states["13:00"], "available")

    def test_half_hour_booking_uses_proportional_price(self) -> None:
        result = self.service.create_booking(
            self.booking(start_time=time(11, 30), duration_hours=0.5)
        )

        self.assertEqual(result.start_time, "11:30")
        self.assertEqual(result.end_time, "12:00")
        self.assertEqual(result.duration_hours, 0.5)
        self.assertEqual(result.total_amount, 600)
        self.assertIn("amount=600", result.payment_link or "")

    def test_schedule_rejects_non_half_hour_increments(self) -> None:
        with self.assertRaises(ValueError):
            self.availability(start_time=time(11, 15))
        with self.assertRaises(ValueError):
            self.availability(duration_hours=0.75)

    def test_booking_rejects_purpose_outside_configured_options(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid booking purpose"):
            self.service.create_booking(self.booking(purpose="Unlisted custom purpose"))

    def test_create_booking_returns_confirmation_and_payment_link(self) -> None:
        result = self.service.create_booking(self.booking())

        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.total_amount, 2400)
        self.assertIn("booking_id=1", result.payment_link or "")
        self.assertTrue(result.calendar_event_id.startswith("gcal_stub_"))
        payment = PaymentService(self.db).get(result.id)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status.value, "pending")
        self.assertEqual(payment.amount, 2400)

    def test_same_space_cannot_be_double_booked(self) -> None:
        self.service.create_booking(self.booking())

        with self.assertRaises(BookingUnavailableError):
            self.service.create_booking(self.booking(customer_email="second@example.com"))

    def test_other_space_can_use_the_same_slot(self) -> None:
        self.service.create_booking(self.booking())

        result = self.service.create_booking(
            self.booking(space_id="premium_large", payment_mode="pay_at_studio")
        )

        self.assertEqual(result.space_name, "Premium Large Space")
        self.assertIsNone(result.payment_link)

    def test_owner_block_prevents_booking_for_only_the_selected_space(self) -> None:
        self.db.add(
            AvailabilityBlock(
                space_id="standard_small",
                booking_date=self.future_date.isoformat(),
                start_time="11:00",
                duration_hours=1.5,
                reason="Equipment maintenance",
            )
        )
        self.db.commit()

        available, message = self.service.check_availability(self.availability())
        other_space, _ = self.service.check_availability(
            self.availability(space_id="premium_large")
        )
        day = self.service.get_day_availability("standard_small", self.future_date)
        states = {slot.start_time: slot.status for slot in day.slots}

        self.assertFalse(available)
        self.assertIn("blocked", message.lower())
        self.assertTrue(other_space)
        self.assertEqual(states["11:00"], "blocked")
        self.assertEqual(states["11:30"], "blocked")
        self.assertEqual(states["12:00"], "blocked")
        self.assertEqual(states["12:30"], "available")
        with self.assertRaises(BookingUnavailableError):
            self.service.create_booking(self.booking())


if __name__ == "__main__":
    unittest.main()
