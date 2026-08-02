import csv
import tempfile
import unittest
from datetime import date, time, timedelta
from http.cookies import SimpleCookie
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import (
    SESSION_COOKIE,
    _session_user,
    admin_availability,
    admin_cancel_booking,
    admin_change_password,
    admin_create_availability_block,
    admin_delete_availability_block,
    admin_export_bookings,
    admin_login,
    admin_overview,
    admin_setup,
    admin_update_booking,
    admin_update_payment,
)
from app.core.config import settings
from app.core.database import Base
from app.models.admin import AdminUser
from app.schemas.admin import (
    AdminChangePasswordRequest,
    AdminAvailabilityBlockCreate,
    AdminBookingUpdate,
    AdminLoginRequest,
    AdminPaymentUpdate,
    AdminSetupRequest,
)
from app.schemas.booking import AvailabilityRequest, WebBookingCreate
from app.services.admin_auth import (
    create_admin_session,
    get_session_secret,
    hash_admin_password,
    read_admin_session,
    verify_admin_password,
)
from app.services.booking_service import BookingApplicationService

settings.email_mode = "console"


def cookie_value(response: Response) -> str:
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie[SESSION_COOKIE].value


class AdminAuthenticationTest(unittest.TestCase):
    def tearDown(self) -> None:
        get_session_secret.cache_clear()

    def test_password_is_salted_and_verified(self) -> None:
        salt_one, digest_one = hash_admin_password("correct-horse-battery-staple")
        salt_two, digest_two = hash_admin_password("correct-horse-battery-staple")

        self.assertTrue(verify_admin_password("correct-horse-battery-staple", salt_one, digest_one))
        self.assertFalse(verify_admin_password("wrong-password", salt_one, digest_one))
        self.assertNotEqual(salt_one, salt_two)
        self.assertNotEqual(digest_one, digest_two)

    def test_session_is_signed_versioned_and_expires(self) -> None:
        secret = "test-secret-that-is-long-enough-for-sessions"
        with patch.object(settings, "admin_session_secret", secret):
            get_session_secret.cache_clear()
            with patch("app.services.admin_auth.time.time", return_value=1000):
                token = create_admin_session("owner", 3)
                session = read_admin_session(token)
                self.assertIsNotNone(session)
                self.assertEqual(session.username, "owner")
                self.assertEqual(session.session_version, 3)
                self.assertIsNone(read_admin_session(f"{token}tampered"))

            expiry = 1000 + settings.admin_session_hours * 60 * 60 + 1
            with patch("app.services.admin_auth.time.time", return_value=expiry):
                self.assertIsNone(read_admin_session(token))

    def test_session_secret_is_generated_once_and_saved_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            secret_file = Path(temp_directory) / "admin-secret"
            with (
                patch.object(settings, "admin_session_secret", ""),
                patch.object(settings, "admin_session_secret_file", str(secret_file)),
            ):
                get_session_secret.cache_clear()
                first = get_session_secret()
                get_session_secret.cache_clear()
                second = get_session_secret()

        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(first, second)

    def test_setup_login_and_password_change_use_the_database(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        secret = "test-secret-that-is-long-enough-for-sessions"

        with Session(engine) as db, patch.object(settings, "admin_session_secret", secret):
            get_session_secret.cache_clear()
            setup_response = Response()
            result = admin_setup(
                AdminSetupRequest(username="owner", password="first-password-123"),
                setup_response,
                db,
            )
            user = db.scalar(select(AdminUser).where(AdminUser.username == "owner"))
            old_token = cookie_value(setup_response)

            self.assertTrue(result.authenticated)
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "first-password-123")
            self.assertIsNotNone(_session_user(old_token, db))

            with self.assertRaises(HTTPException) as duplicate_setup:
                admin_setup(
                    AdminSetupRequest(username="another", password="another-password-123"),
                    Response(),
                    db,
                )
            self.assertEqual(duplicate_setup.exception.status_code, 409)

            with self.assertRaises(HTTPException) as bad_login:
                admin_login(AdminLoginRequest(username="owner", password="wrong-password"), Response(), db)
            self.assertEqual(bad_login.exception.status_code, 401)

            change_response = Response()
            admin_change_password(
                AdminChangePasswordRequest(
                    current_password="first-password-123",
                    new_password="second-password-456",
                ),
                change_response,
                user,
                db,
            )

            self.assertIsNone(_session_user(old_token, db))
            self.assertIsNotNone(_session_user(cookie_value(change_response), db))
            self.assertEqual(user.session_version, 2)
            self.assertFalse(
                verify_admin_password("first-password-123", user.password_salt, user.password_hash)
            )
            self.assertTrue(
                verify_admin_password("second-password-456", user.password_salt, user.password_hash)
            )

            login_response = Response()
            login_result = admin_login(
                AdminLoginRequest(username="owner", password="second-password-456"),
                login_response,
                db,
            )
            self.assertTrue(login_result.authenticated)

    def test_admin_can_block_and_reopen_studio_time(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        booking_date = date.today() + timedelta(days=30)

        with Session(engine) as db:
            created = admin_create_availability_block(
                AdminAvailabilityBlockCreate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(14, 30),
                    duration_hours=1.5,
                    reason="Private production",
                ),
                db,
            )
            day = admin_availability("standard_small", booking_date, db)
            statuses = {slot.start_time: slot for slot in day.slots}

            self.assertEqual(created.start_time, "14:30")
            self.assertEqual(created.end_time, "16:00")
            self.assertEqual(statuses["14:00"].status, "available")
            self.assertEqual(statuses["14:30"].status, "blocked")
            self.assertEqual(statuses["15:00"].block_id, created.id)
            self.assertEqual(statuses["15:30"].reason, "Private production")

            with self.assertRaises(HTTPException) as duplicate:
                admin_create_availability_block(
                    AdminAvailabilityBlockCreate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(15, 30),
                        duration_hours=0.5,
                        reason="Overlap",
                    ),
                    db,
                )
            self.assertEqual(duplicate.exception.status_code, 409)

            response = admin_delete_availability_block(created.id, db)
            reopened = admin_availability("standard_small", booking_date, db)
            reopened_statuses = {slot.start_time: slot.status for slot in reopened.slots}
            self.assertEqual(response.status_code, 204)
            self.assertEqual(reopened_statuses["14:30"], "available")

    def test_admin_can_reschedule_edit_and_cancel_a_booking(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        booking_date = date.today() + timedelta(days=30)

        with Session(engine) as db:
            service = BookingApplicationService(db)

            def booking_payload(start_time: time, email: str) -> WebBookingCreate:
                return WebBookingCreate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=start_time,
                    duration_hours=1,
                    customer_name="Original Customer",
                    customer_email=email,
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                    terms_accepted=True,
                    payment_mode="pay_now",
                )

            original = service.create_booking(booking_payload(time(11), "first@example.com"))
            second = service.create_booking(booking_payload(time(15), "second@example.com"))

            with self.assertRaises(HTTPException) as conflict:
                admin_update_booking(
                    original.id,
                    AdminBookingUpdate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(15),
                        duration_hours=1,
                        customer_name="Updated Customer",
                        customer_email="updated@example.com",
                        phone_number="+918888888888",
                        purpose="Updated portrait shoot",
                    ),
                    db,
                )
            self.assertEqual(conflict.exception.status_code, 409)

            updated = admin_update_booking(
                original.id,
                AdminBookingUpdate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(13, 30),
                    duration_hours=0.5,
                    customer_name="Updated Customer",
                    customer_email="updated@example.com",
                    phone_number="+918888888888",
                    purpose="Updated portrait shoot",
                ),
                db,
            )
            old_slot, _ = service.check_availability(
                AvailabilityRequest(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(11),
                    duration_hours=0.5,
                )
            )

            self.assertEqual(updated.start_time, "13:30")
            self.assertEqual(updated.end_time, "14:00")
            self.assertEqual(updated.customer_name, "Updated Customer")
            self.assertEqual(updated.total_amount, 600)
            self.assertEqual(updated.payment_status, "pending")
            self.assertTrue(old_slot)

            paid = admin_update_payment(
                original.id,
                AdminPaymentUpdate(status="paid", provider_reference="UPI-TEST-001"),
                db,
            )
            overview = admin_overview(db)
            self.assertEqual(paid.payment_status, "paid")
            self.assertEqual(paid.payment_reference, "UPI-TEST-001")
            self.assertEqual(overview.collected_value, 600)
            self.assertEqual(overview.outstanding_value, 1200)

            with self.assertRaises(HTTPException) as paid_price_change:
                admin_update_booking(
                    original.id,
                    AdminBookingUpdate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(13),
                        duration_hours=1,
                        customer_name="Updated Customer",
                        customer_email="updated@example.com",
                        phone_number="+918888888888",
                        purpose="Updated portrait shoot",
                    ),
                    db,
                )
            self.assertEqual(paid_price_change.exception.status_code, 409)

            cancelled = admin_cancel_booking(original.id, db)
            reopened, _ = service.check_availability(
                AvailabilityRequest(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(13, 30),
                    duration_hours=0.5,
                )
            )
            self.assertEqual(cancelled.status, "cancelled")
            self.assertEqual(cancelled.payment_status, "refund_due")
            self.assertTrue(reopened)

            refunded = admin_update_payment(
                original.id,
                AdminPaymentUpdate(status="refunded", provider_reference="REFUND-TEST-001"),
                db,
            )
            self.assertEqual(refunded.payment_status, "refunded")
            self.assertEqual(refunded.payment_reference, "REFUND-TEST-001")

            with self.assertRaises(HTTPException) as duplicate_cancel:
                admin_cancel_booking(original.id, db)
            self.assertEqual(duplicate_cancel.exception.status_code, 409)

            unpaid_cancelled = admin_cancel_booking(second.id, db)
            self.assertEqual(unpaid_cancelled.payment_status, "void")

    def test_csv_export_uses_studio_and_date_filters_and_sanitizes_spreadsheet_formulas(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        first_date = date.today() + timedelta(days=30)
        second_date = first_date + timedelta(days=1)

        with Session(engine) as db:
            service = BookingApplicationService(db)
            for booking_date, customer_name, email in (
                (first_date, "=Formula Customer", "first@example.com"),
                (second_date, "Second Customer", "second@example.com"),
            ):
                service.create_booking(
                    WebBookingCreate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(11),
                        duration_hours=0.5,
                        customer_name=customer_name,
                        customer_email=email,
                        phone_number="+919999999999",
                        purpose="E-commerce",
                        terms_accepted=True,
                        payment_mode="pay_at_studio",
                    )
                )

            service.create_booking(
                WebBookingCreate(
                    space_id="premium_large",
                    booking_date=first_date,
                    start_time=time(11),
                    duration_hours=0.5,
                    customer_name="Other Studio Customer",
                    customer_email="other@example.com",
                    phone_number="+918888888888",
                    purpose="Fashion Shoot",
                    terms_accepted=True,
                    payment_mode="pay_at_studio",
                )
            )

            response = admin_export_bookings(
                space_id="standard_small",
                q=None,
                booking_status=None,
                date_from=first_date,
                date_to=first_date,
                db=db,
            )
            rows = list(csv.reader(StringIO(response.body.decode("utf-8-sig"))))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "Booking reference")
            self.assertEqual(rows[1][8], "'=Formula Customer")
            self.assertEqual(rows[1][13], "600")
            self.assertIn("attachment", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
