import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.config import settings
from app.models.availability import AvailabilityBlock
from app.models.booking import Booking, BookingState
from app.models.notification import AdminNotification
from app.schemas.booking import AvailabilityRequest, WebBookingCreate
from app.services.booking_service import BookingApplicationService, BookingUnavailableError
from app.services.payment_service import PaymentService

settings.email_mode = "console"
settings.calendar_mode = "stub"
settings.razorpay_mode = "stub"


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

    def test_day_availability_fetches_google_calendar_only_once(self) -> None:
        self.service.calendar.mode = "google"
        self.service.calendar.calendar_ids["standard_small"] = "standard-calendar"
        self.service.calendar.service = MagicMock()
        events = self.service.calendar.service.events.return_value
        events.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "owner-hold",
                    "summary": "Owner hold",
                    "start": {"dateTime": f"{self.future_date.isoformat()}T11:00:00+05:30"},
                    "end": {"dateTime": f"{self.future_date.isoformat()}T12:00:00+05:30"},
                }
            ]
        }

        day = self.service.get_day_availability("standard_small", self.future_date)
        states = {slot.start_time: slot.status for slot in day.slots}

        self.assertEqual(len(day.slots), 22)
        self.assertEqual(states["11:00"], "unavailable")
        self.assertEqual(states["11:30"], "unavailable")
        self.assertEqual(states["12:00"], "available")
        events.list.assert_called_once()
        self.assertEqual(events.list.call_args.kwargs["calendarId"], "standard-calendar")

    def test_booking_requires_a_minimum_of_two_hours(self) -> None:
        available, message = self.service.check_availability(
            self.availability(start_time=time(11, 30), duration_hours=1.5)
        )

        self.assertFalse(available)
        self.assertIn("between 2", message)
        with self.assertRaises(ValueError):
            self.booking(start_time=time(11, 30), duration_hours=1.5)

    def test_schedule_rejects_non_half_hour_increments(self) -> None:
        with self.assertRaises(ValueError):
            self.availability(start_time=time(11, 15))
        with self.assertRaises(ValueError):
            self.availability(duration_hours=0.75)

    def test_new_bookings_require_online_payment(self) -> None:
        with self.assertRaisesRegex(ValueError, "Online payment is required"):
            self.booking(payment_mode="pay_at_studio")

    def test_booking_rejects_purpose_outside_configured_options(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid booking purpose"):
            self.service.create_booking(self.booking(purpose="Unlisted custom purpose"))

    def test_create_booking_returns_payment_hold_and_checkout_order(self) -> None:
        self.service.email.send_payment_hold = MagicMock(return_value=True)
        result = self.service.create_booking(self.booking())

        self.assertEqual(result.status, "payment_pending")
        self.assertEqual(result.total_amount, 2000)
        self.assertIsNone(result.payment_link)
        self.assertIsNotNone(result.checkout)
        self.assertEqual(result.checkout.order_id, "order_stub_1")
        self.assertEqual(result.checkout.amount, 200000)
        self.assertIsNone(result.calendar_event_id)
        payment = PaymentService(self.db).get(result.id)
        notification = self.db.query(AdminNotification).filter_by(booking_id=result.id).one_or_none()
        self.assertIsNotNone(payment)
        self.assertIsNone(notification)
        self.assertEqual(payment.status.value, "pending")
        self.assertEqual(payment.amount, 2000)
        self.assertEqual(payment.razorpay_order_id, "order_stub_1")
        stored_booking = self.db.get(Booking, result.id)
        self.assertEqual(stored_booking.terms_accepted, "v1")
        self.assertTrue((stored_booking.calendar_event_id or "").startswith("gcal_stub_"))
        self.service.email.send_payment_hold.assert_called_once_with(
            stored_booking
        )

    def test_stale_unpaid_hold_becomes_expired_and_releases_its_slot(self) -> None:
        result = self.service.create_booking(self.booking())
        booking = self.db.get(Booking, result.id)
        booking.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
        self.db.commit()

        day = self.service.get_day_availability("standard_small", self.future_date)

        states = {slot.start_time: slot.status for slot in day.slots}
        self.assertEqual(booking.state, BookingState.EXPIRED)
        self.assertIsNone(booking.calendar_event_id)
        self.assertEqual(PaymentService(self.db).get(result.id).status.value, "void")
        self.assertEqual(states["11:00"], "available")

    def test_checkout_order_failure_stays_pending_and_retryable(self) -> None:
        self.service.razorpay.create_order = MagicMock(side_effect=OSError("provider unavailable"))

        result = self.service.create_booking(self.booking())

        self.assertEqual(result.status, "payment_pending")
        self.assertEqual(result.payment_mode, "pay_now")
        self.assertIsNone(result.payment_link)
        self.assertIsNone(result.checkout)
        payment = PaymentService(self.db).get(result.id)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.mode.value, "pay_now")
        self.assertEqual(payment.status.value, "pending")

    def test_calendar_hold_failure_does_not_create_a_booking(self) -> None:
        self.service.calendar.create_hold_event = MagicMock(
            side_effect=OSError("calendar unavailable")
        )

        with self.assertRaisesRegex(OSError, "calendar unavailable"):
            self.service.create_booking(self.booking())

        self.assertEqual(self.db.query(Booking).count(), 0)

    def test_paid_booking_is_confirmed_and_creates_calendar_and_notification(self) -> None:
        result = self.service.create_booking(self.booking())
        booking = self.db.get(Booking, result.id)
        hold_event_id = booking.calendar_event_id

        self.service.confirm_paid_booking(booking, "pay_test_001")
        self.db.commit()

        self.assertEqual(booking.state, BookingState.CONFIRMED)
        self.assertTrue((booking.calendar_event_id or "").startswith("gcal_stub_"))
        self.assertEqual(booking.calendar_event_id, hold_event_id)
        self.assertEqual(PaymentService(self.db).get(result.id).status.value, "paid")
        self.assertIsNotNone(self.db.query(AdminNotification).filter_by(booking_id=result.id).one_or_none())

    def test_same_space_cannot_be_double_booked(self) -> None:
        self.service.create_booking(self.booking())

        with self.assertRaises(BookingUnavailableError):
            self.service.create_booking(self.booking(customer_email="second@example.com"))

    def test_parallel_booking_requests_create_only_one_hold(self) -> None:
        with TemporaryDirectory() as temp_directory:
            database_path = Path(temp_directory) / "parallel.sqlite3"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(engine)
            first_holding_lock = Event()
            second_started = Event()
            release_first = Event()

            def attempt(email: str, pause_inside_lock: bool = False) -> str:
                with Session(engine) as db:
                    service = BookingApplicationService(db)
                    if pause_inside_lock:
                        original_create_hold = service.calendar.create_hold_event

                        def delayed_hold(booking: Booking) -> str:
                            first_holding_lock.set()
                            release_first.wait(timeout=5)
                            return original_create_hold(booking)

                        service.calendar.create_hold_event = delayed_hold
                    else:
                        first_holding_lock.wait(timeout=5)
                        second_started.set()
                    try:
                        service.create_booking(self.booking(customer_email=email))
                    except BookingUnavailableError:
                        return "unavailable"
                    return "created"

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(attempt, "first@example.com", True)
                    self.assertTrue(first_holding_lock.wait(timeout=5))
                    second = executor.submit(attempt, "second@example.com")
                    self.assertTrue(second_started.wait(timeout=5))
                    release_first.set()
                    outcomes = {first.result(timeout=5), second.result(timeout=5)}

                with Session(engine) as db:
                    self.assertEqual(db.query(Booking).count(), 1)
                self.assertEqual(outcomes, {"created", "unavailable"})
            finally:
                engine.dispose()

    def test_postgres_booking_guard_uses_a_transaction_advisory_lock(self) -> None:
        db = MagicMock()
        db.bind.dialect.name = "postgresql"
        service = BookingApplicationService(db)

        with service.booking_creation_guard("standard_small", self.future_date):
            pass

        statement = str(db.execute.call_args.args[0])
        self.assertIn("pg_advisory_xact_lock", statement)

    def test_other_space_can_use_the_same_slot(self) -> None:
        self.service.create_booking(self.booking())

        result = self.service.create_booking(
            self.booking(space_id="premium_large")
        )

        self.assertEqual(result.space_name, "Arena")
        self.assertIsNotNone(result.checkout)

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
