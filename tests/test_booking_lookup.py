import unittest
from datetime import date, time, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import admin_cancel_booking, admin_update_payment
from app.api.routes.bookings import lookup_booking
from app.core.database import Base
from app.core.config import settings
from app.schemas.admin import AdminPaymentUpdate
from app.schemas.booking import BookingLookupRequest, WebBookingCreate
from app.services.booking_service import BookingApplicationService

settings.email_mode = "console"
settings.calendar_mode = "stub"


class CustomerBookingLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.booking_date = date.today() + timedelta(days=30)
        self.created = BookingApplicationService(self.db).create_booking(
            WebBookingCreate(
                space_id="standard_small",
                booking_date=self.booking_date,
                start_time=time(14, 30),
                duration_hours=2,
                customer_name="Lookup Customer",
                customer_email="lookup@example.com",
                phone_number="+919999999999",
                purpose="Family Portraits",
                terms_accepted=True,
                payment_mode="pay_now",
            )
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def lookup(self, email: str = "lookup@example.com"):
        return lookup_booking(
            BookingLookupRequest(reference=self.created.reference, customer_email=email),
            self.db,
        )

    def test_reference_and_matching_email_retrieve_booking(self) -> None:
        result = self.lookup()

        self.assertEqual(result.reference, self.created.reference)
        self.assertEqual(result.booking_status, "payment_pending")
        self.assertEqual(result.payment_status, "pending")
        self.assertEqual(result.start_time, "14:30")
        self.assertEqual(result.end_time, "16:30")
        self.assertEqual(result.total_amount, 2400)
        self.assertIsNotNone(result.payment_link)

    def test_wrong_email_returns_same_private_not_found_response(self) -> None:
        with self.assertRaises(HTTPException) as not_found:
            self.lookup("someone-else@example.com")

        self.assertEqual(not_found.exception.status_code, 404)
        self.assertNotIn("lookup@example.com", str(not_found.exception.detail))

    def test_paid_and_cancelled_states_hide_payment_link(self) -> None:
        paid = admin_update_payment(
            self.created.id,
            AdminPaymentUpdate(status="paid", provider_reference="LOOKUP-UPI-001"),
            self.db,
        )
        paid_result = self.lookup()
        self.assertEqual(paid.payment_status, "paid")
        self.assertEqual(paid_result.payment_status, "paid")
        self.assertIsNone(paid_result.payment_link)

        admin_cancel_booking(self.created.id, self.db)
        cancelled_result = self.lookup()
        self.assertEqual(cancelled_result.booking_status, "cancelled")
        self.assertEqual(cancelled_result.payment_status, "refund_due")
        self.assertIsNone(cancelled_result.payment_link)


if __name__ == "__main__":
    unittest.main()
