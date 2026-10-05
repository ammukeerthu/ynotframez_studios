import csv
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from http.cookies import SimpleCookie
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import (
    SESSION_COOKIE,
    _session_user,
    router,
    admin_availability,
    admin_booking_detail,
    admin_bookings,
    admin_bookings_day,
    admin_bookings_heatmap,
    admin_bookings_overview,
    admin_bookings_purpose_month,
    admin_bookings_purpose_year,
    admin_bookings_upcoming,
    admin_bookings_utilization,
    admin_bookings_year_utilization,
    admin_cancel_booking,
    admin_change_password,
    admin_create_availability_block,
    admin_create_offline_booking,
    admin_create_staff_user,
    admin_delete_availability_block,
    admin_delete_availability_block_slot,
    admin_delete_staff_user,
    admin_export_bookings,
    admin_funds_overview,
    admin_funds_cashflow,
    admin_funds_month,
    admin_funds_year,
    admin_login,
    admin_overview,
    admin_alerts,
    admin_read_alert,
    admin_send_expiration_reminder,
    admin_reset_staff_password,
    admin_setup,
    admin_staff_users,
    admin_update_booking,
    admin_update_payment,
    admin_unavailability_overview,
    admin_unavailability_month,
    admin_unavailability_studios,
    admin_unavailability_trend,
    admin_unavailability_upcoming,
    admin_unavailability_year,
    admin_unavailability_collaborations,
    admin_update_collaboration_details,
    require_owner,
    require_admin,
    _operational_alerts,
)
from app.core.config import settings
from app.core.database import Base
from app.models.admin import AdminUser
from app.models.availability import AvailabilityBlock
from app.models.booking import Booking, BookingState, PaymentMode
from app.models.notification import AdminNotification
from app.models.payment import (
    PaymentRecord,
    PaymentStatus,
    PaymentTransaction,
    PaymentTransactionType,
)
from app.schemas.admin import (
    AdminChangePasswordRequest,
    AdminAvailabilityBlockCreate,
    AdminCollaborationDetailsUpdate,
    AdminOfflineBookingCreate,
    AdminBookingUpdate,
    AdminLoginRequest,
    AdminPaymentUpdate,
    AdminSetupRequest,
    AdminStaffPasswordReset,
    AdminStaffUserCreate,
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
settings.calendar_mode = "stub"
settings.razorpay_mode = "stub"


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
            self.assertEqual(result.role, "owner")
            self.assertIsNotNone(user)
            self.assertEqual(user.role, "owner")
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
            self.assertEqual(login_result.role, "owner")

    def test_owner_can_manage_up_to_two_staff_users(self) -> None:
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
            admin_setup(
                AdminSetupRequest(username="owner", password="owner-password-123"),
                Response(),
                db,
            )
            owner = db.scalar(select(AdminUser).where(AdminUser.username == "owner"))
            first = admin_create_staff_user(
                AdminStaffUserCreate(username="frontdesk", password="staff-password-123"),
                owner,
                db,
            )
            second = admin_create_staff_user(
                AdminStaffUserCreate(username="operations", password="staff-password-456"),
                owner,
                db,
            )

            self.assertEqual(first.role, "staff")
            self.assertEqual([user.username for user in admin_staff_users(owner, db)], ["frontdesk", "operations"])
            staff_login = admin_login(
                AdminLoginRequest(username="frontdesk", password="staff-password-123"),
                Response(),
                db,
            )
            self.assertEqual(staff_login.role, "staff")

            with self.assertRaises(HTTPException) as duplicate:
                admin_create_staff_user(
                    AdminStaffUserCreate(username="FrontDesk", password="another-password-123"),
                    owner,
                    db,
                )
            self.assertEqual(duplicate.exception.status_code, 409)

            with self.assertRaises(HTTPException) as too_many:
                admin_create_staff_user(
                    AdminStaffUserCreate(username="thirduser", password="third-password-123"),
                    owner,
                    db,
                )
            self.assertEqual(too_many.exception.status_code, 409)

            staff = db.get(AdminUser, first.id)
            with self.assertRaises(HTTPException) as forbidden:
                require_owner(staff)
            self.assertEqual(forbidden.exception.status_code, 403)

            old_token = create_admin_session(staff.username, staff.session_version)
            admin_reset_staff_password(
                staff.id,
                AdminStaffPasswordReset(password="replacement-password-789"),
                owner,
                db,
            )
            self.assertIsNone(_session_user(old_token, db))
            self.assertTrue(
                verify_admin_password("replacement-password-789", staff.password_salt, staff.password_hash)
            )

            admin_delete_staff_user(second.id, owner, db)
            self.assertEqual([user.username for user in admin_staff_users(owner, db)], ["frontdesk"])

    def test_owner_only_mutations_and_staff_block_permissions_are_declared(self) -> None:
        owner_only = {
            ("/api/admin/staff-users", "GET"),
            ("/api/admin/staff-users", "POST"),
            ("/api/admin/staff-users/{user_id}/reset-password", "POST"),
            ("/api/admin/staff-users/{user_id}", "DELETE"),
            ("/api/admin/studios/{space_id}", "PUT"),
            ("/api/admin/bookings/offline", "POST"),
            ("/api/admin/bookings/{booking_id}", "PATCH"),
            ("/api/admin/bookings/{booking_id}/cancel", "POST"),
            ("/api/admin/bookings/{booking_id}/payment", "POST"),
            ("/api/admin/bookings/{booking_id}/expiration-reminder", "POST"),
        }
        staff_block_access = {
            ("/api/admin/overview/funds", "GET"),
            ("/api/admin/overview/funds/month", "GET"),
            ("/api/admin/overview/funds/year", "GET"),
            ("/api/admin/overview/funds/cashflow", "GET"),
            ("/api/admin/overview/bookings", "GET"),
            ("/api/admin/overview/bookings/day", "GET"),
            ("/api/admin/overview/bookings/upcoming", "GET"),
            ("/api/admin/overview/bookings/utilization", "GET"),
            ("/api/admin/overview/bookings/utilization/year", "GET"),
            ("/api/admin/overview/bookings/purposes/month", "GET"),
            ("/api/admin/overview/bookings/purposes/year", "GET"),
            ("/api/admin/overview/bookings/heatmap", "GET"),
            ("/api/admin/overview/unavailability", "GET"),
            ("/api/admin/overview/unavailability/upcoming", "GET"),
            ("/api/admin/overview/unavailability/month", "GET"),
            ("/api/admin/overview/unavailability/year", "GET"),
            ("/api/admin/overview/unavailability/trend", "GET"),
            ("/api/admin/overview/unavailability/studios", "GET"),
            ("/api/admin/bookings/{booking_id}", "GET"),
            ("/api/admin/availability/blocks", "POST"),
            ("/api/admin/availability/blocks/{block_id}/slot", "DELETE"),
            ("/api/admin/availability/blocks/{block_id}", "DELETE"),
        }
        routes = {
            (route.path, method): route
            for route in router.routes
            for method in route.methods
        }

        for key in owner_only:
            self.assertIn(require_owner, [dependency.call for dependency in routes[key].dependant.dependencies])
        for key in staff_block_access:
            self.assertIn(require_admin, [dependency.call for dependency in routes[key].dependant.dependencies])

    def test_dashboard_analytics_support_period_and_day_pickers(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        studio_today = datetime.now(ZoneInfo(settings.studio_timezone)).date()
        selected_month = studio_today.strftime("%Y-%m")
        next_month = (studio_today.replace(day=28) + timedelta(days=4)).replace(day=1)
        other_month_number = 1 if studio_today.month != 1 else 2
        same_year_other_month = date(studio_today.year, other_month_number, 15)
        previous_year = date(studio_today.year - 1, 6, 15)

        with Session(engine) as db:
            cube = Booking(
                phone_number="+919999999901",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date=studio_today.isoformat(),
                start_time="10:00",
                duration_hours=2,
                customer_name="Cube Customer",
                purpose="Portrait Shoot",
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            arena = Booking(
                phone_number="+919999999902",
                state=BookingState.CONFIRMED,
                space_id="premium_large",
                booking_date=studio_today.isoformat(),
                start_time="14:00",
                duration_hours=1,
                customer_name="Arena Customer",
                purpose="Fashion Shoot",
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            future = Booking(
                phone_number="+919999999903",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date=next_month.isoformat(),
                start_time="09:00",
                duration_hours=1,
                customer_name="Future Customer",
                purpose="Portrait Shoot",
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            cancelled = Booking(
                phone_number="+919999999904",
                state=BookingState.CANCELLED,
                space_id="standard_small",
                booking_date=studio_today.isoformat(),
                start_time="17:00",
                duration_hours=2,
                customer_name="Cancelled Customer",
                purpose="Product Shoot",
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            expired = Booking(
                phone_number="+919999999905",
                state=BookingState.EXPIRED,
                space_id="premium_large",
                booking_date=studio_today.isoformat(),
                start_time="16:00",
                duration_hours=1,
                customer_name="Expired Customer",
                purpose="Portrait Shoot",
                payment_mode=PaymentMode.PAY_NOW,
            )
            db.add_all([cube, arena, future, cancelled, expired])
            db.flush()
            db.add_all(
                [
                    PaymentRecord(
                        booking_id=cube.id,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        amount=2000,
                        status=PaymentStatus.PARTIALLY_PAID,
                        payment_method="upi",
                    ),
                    PaymentRecord(
                        booking_id=arena.id,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        amount=1500,
                        status=PaymentStatus.PAID,
                        payment_method="cash",
                    ),
                    PaymentRecord(
                        booking_id=cancelled.id,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        amount=2000,
                        status=PaymentStatus.REFUND_DUE,
                        payment_method="upi",
                    ),
                    PaymentRecord(
                        booking_id=expired.id,
                        mode=PaymentMode.PAY_NOW,
                        amount=1500,
                        status=PaymentStatus.VOID,
                    ),
                    PaymentTransaction(
                        booking_id=cube.id,
                        transaction_type=PaymentTransactionType.PAYMENT,
                        amount=500,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        payment_method="upi",
                    ),
                    PaymentTransaction(
                        booking_id=arena.id,
                        transaction_type=PaymentTransactionType.PAYMENT,
                        amount=1500,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        payment_method="cash",
                    ),
                    PaymentTransaction(
                        booking_id=cancelled.id,
                        transaction_type=PaymentTransactionType.PAYMENT,
                        amount=2000,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        payment_method="upi",
                    ),
                    PaymentTransaction(
                        booking_id=cancelled.id,
                        transaction_type=PaymentTransactionType.REFUND,
                        amount=500,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        payment_method="upi",
                    ),
                    AvailabilityBlock(
                        space_id="standard_small",
                        booking_date=studio_today.isoformat(),
                        start_time="17:00",
                        duration_hours=2,
                        reason="Collaboration",
                    ),
                    AvailabilityBlock(
                        space_id="premium_large",
                        booking_date=studio_today.isoformat(),
                        start_time="18:00",
                        duration_hours=1,
                        reason="Maintenance",
                    ),
                    AvailabilityBlock(
                        space_id="standard_small",
                        booking_date=same_year_other_month.isoformat(),
                        start_time="12:00",
                        duration_hours=4,
                        reason="Maintenance",
                    ),
                    AvailabilityBlock(
                        space_id="premium_large",
                        booking_date=previous_year.isoformat(),
                        start_time="12:00",
                        duration_hours=5,
                        reason="Technical Issue",
                    ),
                ]
            )
            db.commit()

            monthly_funds = admin_funds_overview(selected_month, db)
            overall_funds = admin_funds_overview(None, db)
            cube_funds = admin_funds_overview(
                selected_month,
                db,
                year=studio_today.year,
                space_id="standard_small",
            )
            bookings = admin_bookings_overview(0, selected_month, db)
            cube_bookings = admin_bookings_overview(
                0,
                selected_month,
                db,
                space_id="standard_small",
            )
            unavailability = admin_unavailability_overview(
                selected_month,
                db,
                year=studio_today.year,
            )
            cube_unavailability = admin_unavailability_overview(
                selected_month,
                db,
                year=studio_today.year,
                space_id="standard_small",
            )
            funds_month_panel = admin_funds_month(selected_month, db)
            funds_year_panel = admin_funds_year(studio_today.year, db)
            funds_cashflow_panel = admin_funds_cashflow(studio_today.year, db)
            bookings_day_panel = admin_bookings_day(0, db)
            bookings_upcoming_panel = admin_bookings_upcoming(studio_today, next_month, db)
            bookings_utilization_panel = admin_bookings_utilization(selected_month, db)
            bookings_year_utilization_panel = admin_bookings_year_utilization(studio_today.year, db)
            bookings_purpose_month_panel = admin_bookings_purpose_month(selected_month, db)
            bookings_purpose_year_panel = admin_bookings_purpose_year(studio_today.year, db)
            bookings_heatmap_panel = admin_bookings_heatmap(selected_month, db)
            unavailability_month_panel = admin_unavailability_month(selected_month, db)
            unavailability_year_panel = admin_unavailability_year(studio_today.year, db)
            unavailability_trend_panel = admin_unavailability_trend(studio_today.year, db)
            unavailability_studios_panel = admin_unavailability_studios(selected_month, db)

            self.assertEqual(monthly_funds.estimated_amount, 3500)
            self.assertEqual(monthly_funds.collected_amount, 2000)
            self.assertEqual(monthly_funds.outstanding_amount, 1500)
            self.assertEqual(overall_funds.estimated_amount, 4500)
            self.assertEqual(overall_funds.outstanding_amount, 2500)
            self.assertEqual(overall_funds.summary_collected_amount, 2000)
            self.assertEqual(monthly_funds.month_estimated_amount, 3500)
            self.assertEqual(monthly_funds.month_pending_amount, 1500)
            self.assertEqual(funds_month_panel.pending_amount, 1500)
            self.assertEqual(funds_year_panel.year, studio_today.year)
            self.assertEqual(funds_year_panel.collections[studio_today.month - 1].estimated_amount, 3500)
            self.assertEqual(
                funds_cashflow_panel.cashflow[studio_today.month - 1].net_amount,
                3500,
            )
            current_month_collection = monthly_funds.yearly_collections[studio_today.month - 1]
            self.assertEqual(current_month_collection.month, studio_today.month)
            self.assertEqual(current_month_collection.estimated_amount, 3500)
            self.assertEqual(current_month_collection.collected_amount, 2000)
            self.assertEqual(current_month_collection.pending_amount, 1500)
            self.assertEqual(cube_funds.summary_estimated_amount, 3000)
            self.assertEqual(cube_funds.summary_collected_amount, 500)
            self.assertEqual(cube_funds.month_pending_amount, 1500)
            self.assertEqual(len(cube_funds.yearly_collections), 12)
            current_month_cashflow = monthly_funds.yearly_cashflow[studio_today.month - 1]
            self.assertEqual(current_month_cashflow.received_amount, 4000)
            self.assertEqual(current_month_cashflow.refunded_amount, 500)
            self.assertEqual(current_month_cashflow.net_amount, 3500)
            self.assertEqual(
                [item.customer_name for item in monthly_funds.outstanding_bookings],
                ["Cube Customer", "Future Customer"],
            )
            self.assertEqual(
                [item.balance_due for item in monthly_funds.outstanding_bookings],
                [1500, 1000],
            )
            ageing = {item.key: item for item in monthly_funds.outstanding_ageing}
            self.assertEqual(ageing["upcoming"].amount + sum(
                ageing[key].amount
                for key in ("overdue_1_7", "overdue_8_30", "overdue_31_plus")
            ), 2500)
            self.assertEqual(
                cube_funds.yearly_cashflow[studio_today.month - 1].received_amount,
                2500,
            )
            self.assertEqual(bookings.selected_date, studio_today.isoformat())
            self.assertIsNone(bookings.space_id)
            self.assertEqual(bookings.summary_total_bookings, 5)
            self.assertEqual(bookings.summary_confirmed_bookings, 3)
            self.assertEqual(bookings.summary_cancelled_bookings, 1)
            self.assertEqual(bookings.summary_expired_bookings, 1)
            self.assertEqual([item.id for item in bookings.expired_bookings], [expired.id])
            self.assertEqual(bookings.expired_bookings[0].payment_status, "void")
            self.assertEqual(bookings.total_bookings, 2)
            self.assertEqual(bookings_day_panel.total_bookings, 2)
            self.assertIn(future.id, {item.id for item in bookings_upcoming_panel.bookings})
            self.assertEqual(bookings_utilization_panel.month, selected_month)
            self.assertEqual(bookings_year_utilization_panel.year, studio_today.year)
            self.assertEqual(
                {item.space_name for item in bookings_year_utilization_panel.studios},
                {"Cube", "Arena"},
            )
            self.assertEqual(bookings_purpose_month_panel.month, selected_month)
            self.assertEqual(
                {item.purpose for item in bookings_purpose_month_panel.purposes},
                {"Portrait Shoot", "Fashion Shoot"},
            )
            self.assertEqual(bookings_purpose_year_panel.year, studio_today.year)
            self.assertEqual(
                sum(item.booking_count for item in bookings_purpose_year_panel.purposes),
                3,
            )
            self.assertEqual(bookings_heatmap_panel.month, selected_month)
            self.assertEqual([item.space_name for item in bookings.bookings], ["Cube", "Arena"])
            cube_heatmap_cell = next(
                item
                for item in bookings.utilization_heatmap
                if item.space_id == "standard_small"
                and item.weekday == studio_today.weekday()
                and item.time_slot == "10:00"
            )
            self.assertEqual(cube_heatmap_cell.booked_occurrences, 1)
            self.assertGreater(cube_heatmap_cell.utilization_percent, 0)
            action_ids = {item.id for item in bookings.action_items}
            self.assertIn(f"calendar-missing-{future.id}", action_ids)
            self.assertIn(f"payment-{future.id}", action_ids)
            self.assertEqual(cube_bookings.space_id, "standard_small")
            self.assertEqual(cube_bookings.total_bookings, 1)
            self.assertEqual([item.space_name for item in cube_bookings.bookings], ["Cube"])
            self.assertEqual(
                {item.space_id for item in cube_bookings.studio_utilization},
                {"standard_small"},
            )
            self.assertEqual(
                {item.space_id for item in cube_bookings.utilization_heatmap},
                {"standard_small"},
            )
            self.assertTrue(
                all(item.space_id == "standard_small" for item in cube_bookings.action_items)
            )
            utilization = {item.space_id: item for item in bookings.studio_utilization}
            self.assertEqual(utilization["standard_small"].booked_hours, 2)
            self.assertEqual(utilization["premium_large"].booked_hours, 1)
            self.assertGreater(utilization["standard_small"].available_hours, 0)
            self.assertEqual(unavailability.total_blocked_hours, 3)
            self.assertEqual(
                [(item.reason, item.blocked_hours) for item in unavailability.reasons],
                [("Collaboration", 2), ("Maintenance", 1)],
            )
            self.assertEqual(unavailability.summary_total_blocked_hours, 12)
            self.assertEqual(unavailability.month_total_blocked_hours, 3)
            self.assertEqual(unavailability_month_panel.total_blocked_hours, 3)
            self.assertEqual(unavailability_year_panel.total_blocked_hours, 7)
            self.assertEqual(
                unavailability_trend_panel.months[studio_today.month - 1].blocked_hours,
                3,
            )
            self.assertEqual(
                {item.space_name for item in unavailability_studios_panel.studios},
                {"Cube", "Arena"},
            )
            self.assertEqual(unavailability.year_total_blocked_hours, 7)
            self.assertEqual(
                [(item.reason, item.blocked_hours) for item in unavailability.year_reasons],
                [("Maintenance", 5), ("Collaboration", 2)],
            )
            self.assertEqual(cube_unavailability.summary_total_blocked_hours, 6)
            self.assertEqual(cube_unavailability.month_total_blocked_hours, 2)
            self.assertEqual(cube_unavailability.year_total_blocked_hours, 6)
            self.assertEqual(
                unavailability.yearly_blocked_hours[studio_today.month - 1].blocked_hours,
                3,
            )
            self.assertEqual(
                unavailability.yearly_blocked_hours[other_month_number - 1].blocked_hours,
                4,
            )
            self.assertEqual(
                [(item.space_name, item.blocked_hours) for item in unavailability.month_studio_hours],
                [("Cube", 2), ("Arena", 1)],
            )
            self.assertEqual(
                [(item.space_name, item.blocked_hours) for item in cube_unavailability.month_studio_hours],
                [("Cube", 2)],
            )

            with self.assertRaises(HTTPException) as invalid_month:
                admin_funds_overview("2026-13", db)
            self.assertEqual(invalid_month.exception.status_code, 400)

            with self.assertRaises(HTTPException) as invalid_booking_space:
                admin_bookings_overview(
                    0,
                    selected_month,
                    db,
                    space_id="missing-space",
                )
            self.assertEqual(invalid_booking_space.exception.status_code, 404)

    def test_funds_age_outstanding_balances_from_the_session_end(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        studio_today = datetime.now(ZoneInfo(settings.studio_timezone)).date()

        with Session(engine) as db:
            cases = [
                (-3, 100, "overdue_1_7"),
                (-10, 200, "overdue_8_30"),
                (-40, 300, "overdue_31_plus"),
                (3, 400, "upcoming"),
            ]
            bookings = []
            for index, (day_offset, amount, _) in enumerate(cases):
                booking = Booking(
                    phone_number=f"+919999998{index:03d}",
                    state=BookingState.CONFIRMED,
                    space_id="standard_small",
                    booking_date=(studio_today + timedelta(days=day_offset)).isoformat(),
                    start_time="09:00",
                    duration_hours=1,
                    customer_name=f"Ageing Customer {index}",
                    payment_mode=PaymentMode.PAY_AT_STUDIO,
                    calendar_event_id=f"event-{index}",
                )
                db.add(booking)
                db.flush()
                db.add(
                    PaymentRecord(
                        booking_id=booking.id,
                        mode=PaymentMode.PAY_AT_STUDIO,
                        amount=amount,
                        status=PaymentStatus.PENDING,
                    )
                )
                bookings.append(booking)
            db.commit()

            overview = admin_funds_overview(None, db)
            buckets = {item.key: item for item in overview.outstanding_ageing}
            for (_, amount, key), booking in zip(cases, bookings, strict=True):
                self.assertEqual(buckets[key].amount, amount)
                self.assertEqual(buckets[key].booking_count, 1)
                item = next(row for row in overview.outstanding_bookings if row.id == booking.id)
                self.assertEqual(item.ageing_bucket, key)

    def test_unavailability_lists_only_upcoming_blocks_in_selected_range(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        studio_today = datetime.now(ZoneInfo(settings.studio_timezone)).date()
        tomorrow = studio_today + timedelta(days=1)

        with Session(engine) as db:
            db.add_all(
                [
                    AvailabilityBlock(
                        space_id="standard_small",
                        booking_date=(studio_today - timedelta(days=1)).isoformat(),
                        start_time="10:00",
                        duration_hours=2,
                        reason="Collaboration",
                    ),
                    AvailabilityBlock(
                        space_id="standard_small",
                        booking_date=tomorrow.isoformat(),
                        start_time="10:00",
                        duration_hours=2,
                        reason="Collaboration",
                    ),
                    AvailabilityBlock(
                        space_id="premium_large",
                        booking_date=tomorrow.isoformat(),
                        start_time="13:00",
                        duration_hours=1,
                        reason="Maintenance",
                    ),
                    AvailabilityBlock(
                        space_id="premium_large",
                        booking_date=(studio_today + timedelta(days=8)).isoformat(),
                        start_time="15:00",
                        duration_hours=1.5,
                        reason="Collaboration",
                    ),
                ]
            )
            db.commit()

            overview = admin_unavailability_overview(
                studio_today.strftime("%Y-%m"),
                db,
                year=studio_today.year,
                date_from=studio_today,
                date_to=studio_today + timedelta(days=7),
            )
            panel = admin_unavailability_upcoming(
                date_from=studio_today,
                date_to=studio_today + timedelta(days=7),
                db=db,
            )

            self.assertEqual(overview.blocked_date_from, studio_today.isoformat())
            self.assertEqual(
                overview.blocked_date_to,
                (studio_today + timedelta(days=7)).isoformat(),
            )
            self.assertEqual(len(overview.upcoming_blocks), 2)
            self.assertEqual(panel.date_from, studio_today.isoformat())
            self.assertEqual(panel.date_to, (studio_today + timedelta(days=7)).isoformat())
            self.assertEqual(len(panel.blocks), 2)
            collaboration, maintenance = overview.upcoming_blocks
            self.assertEqual(collaboration.booking_date, tomorrow.isoformat())
            self.assertEqual(collaboration.start_time, "10:00")
            self.assertEqual(collaboration.end_time, "12:00")
            self.assertEqual(collaboration.space_name, "Cube")
            self.assertEqual(collaboration.duration_hours, 2)
            self.assertEqual(collaboration.reason, "Collaboration")
            self.assertEqual(maintenance.start_time, "13:00")
            self.assertEqual(maintenance.space_name, "Arena")
            self.assertEqual(maintenance.reason, "Maintenance")

            with self.assertRaises(HTTPException) as reversed_range:
                admin_unavailability_overview(
                    studio_today.strftime("%Y-%m"),
                    db,
                    date_from=tomorrow,
                    date_to=studio_today,
                )
            self.assertEqual(reversed_range.exception.status_code, 400)

    def test_availability_booking_tile_exposes_read_only_booking_details(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        booking_date = date.today() + timedelta(days=30)

        with Session(engine) as db:
            booking = Booking(
                phone_number="+919999999999",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date=booking_date.isoformat(),
                start_time="14:30",
                duration_hours=1,
                customer_name="Calendar Customer",
                customer_email="calendar@example.com",
                purpose="Fine Arts",
                terms_accepted="yes",
                payment_mode=PaymentMode.PAY_AT_STUDIO,
            )
            db.add(booking)
            db.flush()
            db.add(
                PaymentRecord(
                    booking_id=booking.id,
                    mode=PaymentMode.PAY_AT_STUDIO,
                    amount=1000,
                    status=PaymentStatus.PENDING,
                    payment_method="upi",
                )
            )
            db.commit()

            day = admin_availability("standard_small", booking_date, db)
            booked_slot = next(slot for slot in day.slots if slot.start_time == "14:30")
            details = admin_booking_detail(booking.id, db)

            self.assertEqual(booked_slot.status, "booked")
            self.assertEqual(booked_slot.booking_id, booking.id)
            self.assertEqual(booked_slot.booking_reference, f"YNF-{booking.id:06d}")
            self.assertEqual(details.reference, f"YNF-{booking.id:06d}")
            self.assertEqual(details.customer_name, "Calendar Customer")
            self.assertEqual(details.phone_number, "+919999999999")
            self.assertEqual(details.space_name, "Cube")
            self.assertEqual(details.purpose, "Fine Arts")
            self.assertEqual(details.payment_status, "pending")
            self.assertEqual(details.status, "confirmed")

            with self.assertRaises(HTTPException) as missing:
                admin_booking_detail(999999, db)
            self.assertEqual(missing.exception.status_code, 404)

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
                    duration_hours=2,
                    reason="Private production",
                ),
                db,
            )
            day = admin_availability("standard_small", booking_date, db)
            statuses = {slot.start_time: slot for slot in day.slots}

            self.assertEqual(created.start_time, "14:30")
            self.assertEqual(created.end_time, "16:30")
            self.assertTrue(
                db.get(AvailabilityBlock, created.id).calendar_event_id.startswith("gcal_stub_block_")
            )
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
                        duration_hours=2,
                        reason="Overlap",
                    ),
                    db,
                )
            self.assertEqual(duplicate.exception.status_code, 409)

            with self.assertRaises(ValueError):
                AdminAvailabilityBlockCreate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(17),
                    duration_hours=0.25,
                    reason="Too short",
                )

            split_response = admin_delete_availability_block_slot(created.id, time(15), db)
            split_day = admin_availability("standard_small", booking_date, db)
            split_statuses = {slot.start_time: slot for slot in split_day.slots}
            remaining_blocks = list(db.scalars(select(AvailabilityBlock)))
            self.assertEqual(split_response.status_code, 204)
            self.assertEqual(split_statuses["14:30"].status, "blocked")
            self.assertEqual(split_statuses["15:00"].status, "available")
            self.assertEqual(split_statuses["15:30"].status, "blocked")
            self.assertEqual(split_statuses["16:00"].status, "blocked")
            self.assertEqual(len(remaining_blocks), 2)
            self.assertTrue(all(block.calendar_event_id for block in remaining_blocks))
            self.assertEqual(len({block.calendar_event_id for block in remaining_blocks}), 2)
            self.assertEqual(
                {(block.start_time, block.duration_hours) for block in remaining_blocks},
                {("14:30", 0.5), ("15:30", 1.0)},
            )

            response = admin_delete_availability_block(created.id, db)
            reopened = admin_availability("standard_small", booking_date, db)
            reopened_statuses = {slot.start_time: slot.status for slot in reopened.slots}
            self.assertEqual(response.status_code, 204)
            self.assertEqual(reopened_statuses["14:30"], "available")

            half_hour = admin_create_availability_block(
                AdminAvailabilityBlockCreate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(17),
                    duration_hours=0.5,
                    reason="Quick reset",
                ),
                db,
            )
            half_hour_response = admin_delete_availability_block_slot(half_hour.id, time(17), db)
            half_hour_day = admin_availability("standard_small", booking_date, db)
            half_hour_statuses = {slot.start_time: slot.status for slot in half_hour_day.slots}
            self.assertEqual(half_hour_response.status_code, 204)
            self.assertEqual(half_hour_statuses["17:00"], "available")

    def test_admin_can_create_a_historical_studio_block(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        booking_date = date.today() - timedelta(days=30)
        owner = AdminUser(
            username="owner",
            password_salt="salt",
            password_hash="hash",
            role="owner",
            session_version=1,
        )
        staff = AdminUser(
            username="staff",
            password_salt="salt",
            password_hash="hash",
            role="staff",
            session_version=1,
        )

        with Session(engine) as db:
            created = admin_create_availability_block(
                AdminAvailabilityBlockCreate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(14, 30),
                    duration_hours=1,
                    reason="Collaboration",
                    collaboration_name="Legacy Creative Team",
                ),
                db,
                user=owner,
            )
            day = admin_availability("standard_small", booking_date, db)
            statuses = {slot.start_time: slot for slot in day.slots}

            self.assertEqual(created.reason, "Collaboration")
            self.assertEqual(statuses["14:00"].status, "past")
            self.assertEqual(statuses["14:30"].status, "blocked")
            self.assertEqual(statuses["15:00"].status, "blocked")
            self.assertEqual(statuses["15:00"].block_id, created.id)

            with self.assertRaises(HTTPException) as staff_past_block:
                admin_create_availability_block(
                    AdminAvailabilityBlockCreate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(16),
                        duration_hours=1,
                        reason="Maintenance",
                    ),
                    db,
                    user=staff,
                )
            self.assertEqual(staff_past_block.exception.status_code, 403)
            self.assertIn("Only the owner", staff_past_block.exception.detail)

            staff_future_block = admin_create_availability_block(
                AdminAvailabilityBlockCreate(
                    space_id="standard_small",
                    booking_date=date.today() + timedelta(days=30),
                    start_time=time(16),
                    duration_hours=1,
                    reason="Maintenance",
                ),
                db,
                user=staff,
            )
            self.assertEqual(staff_future_block.reason, "Maintenance")

    def test_collaboration_usage_report_and_owner_backfill(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        owner = AdminUser(
            username="owner",
            password_salt="salt",
            password_hash="hash",
            role="owner",
            session_version=1,
        )
        with Session(engine) as db:
            block = AvailabilityBlock(
                space_id="premium_large",
                booking_date="2026-10-01",
                start_time="09:00",
                duration_hours=3,
                reason="Collaboration",
                calendar_event_id="gcal_stub_block_legacy",
            )
            db.add(block)
            db.commit()
            db.refresh(block)

            before = admin_unavailability_collaborations(
                period="month", month="2026-10", year=None, db=db, space_id=None
            )
            self.assertEqual(before.total_hours, 3)
            self.assertEqual(before.total_sessions, 1)
            self.assertEqual(before.unique_collaborators, 0)
            self.assertTrue(before.records[0].details_missing)

            updated = admin_update_collaboration_details(
                block.id,
                AdminCollaborationDetailsUpdate(
                    collaboration_name="North Star Collective",
                    collaboration_contact="team@example.com",
                    collaboration_details="Editorial test shoot",
                ),
                db,
                owner,
            )
            self.assertEqual(updated.collaboration_name, "North Star Collective")
            self.assertEqual(updated.collaboration_recorded_by, "owner")

            after = admin_unavailability_collaborations(
                period="year", month=None, year=2026, db=db, space_id="premium_large"
            )
            self.assertEqual(after.unique_collaborators, 1)
            self.assertEqual(after.collaborators[0].collaborator_name, "North Star Collective")
            self.assertEqual(after.collaborators[0].sessions, 1)
            self.assertFalse(after.records[0].details_missing)

            with self.assertRaises(ValueError):
                AdminAvailabilityBlockCreate(
                    space_id="premium_large",
                    booking_date=date(2026, 10, 2),
                    start_time=time(9),
                    duration_hours=1,
                    reason="Collaboration",
                )

    def test_alerts_include_new_booking_start_and_end_handover_reminders(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            now = datetime(2026, 9, 20, 14, 5)
            current = Booking(
                phone_number="+919999999991",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date="2026-09-20",
                start_time="13:15",
                duration_hours=1,
                customer_name="Current Customer",
                customer_email="current@example.com",
                purpose="Fashion Shoot",
            )
            upcoming = Booking(
                phone_number="+919999999992",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date="2026-09-20",
                start_time="14:20",
                duration_hours=1,
                customer_name="Next Customer",
                customer_email="next@example.com",
                purpose="Editorial",
            )
            db.add_all([current, upcoming])
            db.flush()
            notification = AdminNotification(booking_id=upcoming.id)
            db.add(notification)
            db.commit()

            operational = _operational_alerts(db, now)
            kinds = {alert.kind for alert in operational}
            ending = next(alert for alert in operational if alert.kind == "ends_soon")
            response = admin_alerts(db)

            self.assertEqual(kinds, {"starts_soon", "ends_soon"})
            self.assertIn("Next Customer", ending.message)
            self.assertEqual(response.unread_count, 1)
            self.assertEqual(response.new_bookings[0].booking_id, upcoming.id)
            self.assertEqual(response.new_bookings[0].title, "New booking · Cube")
            self.assertFalse(response.new_bookings[0].is_read)

            admin_read_alert(notification.id, db)
            read_response = admin_alerts(db)
            self.assertEqual(read_response.unread_count, 0)
            self.assertEqual(len(read_response.new_bookings), 1)
            self.assertTrue(read_response.new_bookings[0].is_read)

            notification.kind = "booking_request"
            db.commit()
            request_response = admin_alerts(db)
            self.assertEqual(request_response.new_bookings[0].title, "Booking request · Cube")
            self.assertIn("payment is pending", request_response.new_bookings[0].message)

            notification.kind = "booking_expired"
            db.commit()
            expired_response = admin_alerts(db)
            self.assertEqual(
                expired_response.new_bookings[0].title,
                "Booking request expired · Cube",
            )
            self.assertIn("slot was released", expired_response.new_bookings[0].message)

    def test_expired_booking_reminder_requires_future_unrebooked_session(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        studio_today = datetime.now(ZoneInfo(settings.studio_timezone)).date()
        created_at = datetime.now() - timedelta(hours=3)
        future_date = (studio_today + timedelta(days=7)).isoformat()

        with Session(engine) as db:
            eligible = Booking(
                phone_number="+919111111111",
                state=BookingState.EXPIRED,
                space_id="standard_small",
                booking_date=future_date,
                start_time="10:00",
                duration_hours=1,
                customer_name="Eligible Customer",
                customer_email="eligible@example.com",
                purpose="Fashion Shoot",
                payment_mode=PaymentMode.PAY_NOW,
                created_at=created_at,
                updated_at=created_at,
            )
            rebooked_hold = Booking(
                phone_number="+919222222222",
                state=BookingState.EXPIRED,
                space_id="standard_small",
                booking_date=future_date,
                start_time="11:00",
                duration_hours=1,
                customer_name="Rebooked Customer",
                customer_email="old-address@example.com",
                purpose="Fashion Shoot",
                payment_mode=PaymentMode.PAY_NOW,
                created_at=created_at,
                updated_at=created_at,
            )
            replacement = Booking(
                phone_number="92222 22222",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date=future_date,
                start_time="14:00",
                duration_hours=1,
                customer_name="Rebooked Customer",
                customer_email="new-address@example.com",
                purpose="Fashion Shoot",
                payment_mode=PaymentMode.PAY_NOW,
                created_at=created_at + timedelta(hours=1),
                updated_at=created_at + timedelta(hours=1),
            )
            other_customer_same_slot = Booking(
                phone_number="+919444444444",
                state=BookingState.CONFIRMED,
                space_id="standard_small",
                booking_date=future_date,
                start_time="10:00",
                duration_hours=1,
                customer_name="Different Customer",
                customer_email="different@example.com",
                purpose="Fashion Shoot",
                payment_mode=PaymentMode.PAY_NOW,
                created_at=created_at + timedelta(hours=1),
                updated_at=created_at + timedelta(hours=1),
            )
            elapsed = Booking(
                phone_number="+919333333333",
                state=BookingState.EXPIRED,
                space_id="standard_small",
                booking_date=(studio_today - timedelta(days=1)).isoformat(),
                start_time="10:00",
                duration_hours=1,
                customer_name="Elapsed Customer",
                customer_email="elapsed@example.com",
                purpose="Fashion Shoot",
                payment_mode=PaymentMode.PAY_NOW,
                created_at=created_at,
                updated_at=created_at,
            )
            db.add_all(
                [eligible, rebooked_hold, replacement, other_customer_same_slot, elapsed]
            )
            db.commit()

            overview = admin_bookings_overview(day_offset=0, month=None, db=db)
            expired_by_id = {item.id: item for item in overview.expired_bookings}
            self.assertTrue(expired_by_id[eligible.id].reminder_eligible)
            self.assertEqual(expired_by_id[eligible.id].reminder_status, "eligible")
            self.assertFalse(expired_by_id[rebooked_hold.id].reminder_eligible)
            self.assertEqual(expired_by_id[rebooked_hold.id].reminder_status, "rebooked")
            self.assertEqual(
                expired_by_id[rebooked_hold.id].rebooked_reference,
                f"YNF-{replacement.id:06d}",
            )
            self.assertEqual(expired_by_id[elapsed.id].reminder_status, "session_elapsed")

            with patch(
                "app.services.email_service.EmailService.send_booking_expired",
                return_value=True,
            ) as send_email:
                response = admin_send_expiration_reminder(eligible.id, db)

                self.assertEqual(response.reference, f"YNF-{eligible.id:06d}")
                self.assertIsNotNone(eligible.expiration_reminder_sent_at)
                send_email.assert_called_once_with(eligible)
                with self.assertRaises(HTTPException) as already_sent:
                    admin_send_expiration_reminder(eligible.id, db)
                self.assertEqual(already_sent.exception.status_code, 409)
                send_email.assert_called_once_with(eligible)

            with self.assertRaises(HTTPException) as customer_rebooked:
                admin_send_expiration_reminder(rebooked_hold.id, db)
            self.assertEqual(customer_rebooked.exception.status_code, 409)
            self.assertIn(f"YNF-{replacement.id:06d}", customer_rebooked.exception.detail)

            with self.assertRaises(HTTPException) as session_elapsed:
                admin_send_expiration_reminder(elapsed.id, db)
            self.assertEqual(session_elapsed.exception.status_code, 409)
            self.assertIn("elapsed", session_elapsed.exception.detail)

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
                    duration_hours=2,
                    customer_name="Original Customer",
                    customer_email=email,
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                    terms_accepted=True,
                    payment_mode="pay_now",
                )

            original = service.create_booking(booking_payload(time(11), "first@example.com"))
            second = service.create_booking(booking_payload(time(15), "second@example.com"))
            # Simulate legacy confirmed-but-unpaid records for the admin lifecycle test.
            db.get(Booking, original.id).state = BookingState.CONFIRMED
            db.get(Booking, second.id).state = BookingState.CONFIRMED
            db.commit()

            edit_day = admin_availability(
                "standard_small",
                booking_date,
                db,
                exclude_booking_id=original.id,
            )
            edit_statuses = {slot.start_time: slot.status for slot in edit_day.slots}
            self.assertEqual(edit_statuses["11:00"], "available")
            self.assertEqual(edit_statuses["11:30"], "available")
            self.assertEqual(edit_statuses["15:00"], "booked")

            with self.assertRaises(HTTPException) as conflict:
                admin_update_booking(
                    original.id,
                    AdminBookingUpdate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(15),
                        duration_hours=2,
                        customer_name="Original Customer",
                        customer_email="updated@example.com",
                        phone_number="+919999999999",
                        purpose="Fashion Shoot",
                    ),
                    db,
                )
            self.assertEqual(conflict.exception.status_code, 409)

            with self.assertRaises(HTTPException) as immutable_details:
                admin_update_booking(
                    original.id,
                    AdminBookingUpdate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(11),
                        duration_hours=2,
                        customer_name="Changed Customer",
                        customer_email="updated@example.com",
                        phone_number="+919999999999",
                        purpose="Fashion Shoot",
                    ),
                    db,
                )
            self.assertEqual(immutable_details.exception.status_code, 409)
            self.assertIn("cannot be changed", immutable_details.exception.detail)

            updated = admin_update_booking(
                original.id,
                AdminBookingUpdate(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(13),
                    duration_hours=2,
                    customer_name="Original Customer",
                    customer_email="updated@example.com",
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                ),
                db,
            )
            old_slot, _ = service.check_availability(
                AvailabilityRequest(
                    space_id="standard_small",
                    booking_date=booking_date,
                    start_time=time(11),
                    duration_hours=2,
                )
            )

            self.assertEqual(updated.start_time, "13:00")
            self.assertEqual(updated.end_time, "15:00")
            self.assertEqual(updated.customer_name, "Original Customer")
            self.assertEqual(updated.purpose, "Fashion Shoot")
            self.assertEqual(updated.terms_accepted, "v2")
            self.assertEqual(updated.total_amount, 2000)
            self.assertEqual(updated.payment_status, "pending")
            self.assertTrue(old_slot)

            paid = admin_update_payment(
                original.id,
                AdminPaymentUpdate(
                    status="paid",
                    provider_reference="UPI-TEST-001",
                    payment_method="upi",
                ),
                db,
            )
            overview = admin_overview(db)
            self.assertEqual(paid.payment_status, "paid")
            self.assertEqual(paid.payment_reference, "UPI-TEST-001")
            self.assertEqual(overview.collected_value, 2000)
            self.assertEqual(overview.outstanding_value, 2000)

            upgraded = admin_update_booking(
                original.id,
                AdminBookingUpdate(
                    space_id="premium_large",
                    booking_date=booking_date,
                    start_time=time(12, 30),
                    duration_hours=2,
                    customer_name="Original Customer",
                    customer_email="updated@example.com",
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                ),
                db,
            )
            self.assertEqual(upgraded.space_id, "premium_large")
            self.assertEqual(upgraded.total_amount, 3000)
            self.assertEqual(upgraded.amount_paid, 2000)
            self.assertEqual(upgraded.balance_due, 1000)
            self.assertEqual(upgraded.payment_status, "partially_paid")
            self.assertEqual(
                [(entry.amount, entry.provider_reference) for entry in upgraded.payment_transactions],
                [(2000, "UPI-TEST-001")],
            )

            with self.assertRaises(HTTPException) as downgrade:
                admin_update_booking(
                    original.id,
                    AdminBookingUpdate(
                        space_id="standard_small",
                        booking_date=booking_date,
                        start_time=time(13),
                        duration_hours=2,
                        customer_name="Original Customer",
                        customer_email="updated@example.com",
                        phone_number="+919999999999",
                        purpose="Fashion Shoot",
                    ),
                    db,
                )
            self.assertEqual(downgrade.exception.status_code, 409)

            upgrade_paid = admin_update_payment(
                original.id,
                AdminPaymentUpdate(
                    status="paid",
                    amount=1000,
                    provider_reference="BANK-UPGRADE-001",
                    payment_method="bank_transfer",
                ),
                db,
            )
            self.assertEqual(upgrade_paid.payment_status, "paid")
            self.assertEqual(upgrade_paid.amount_paid, 3000)
            self.assertEqual(upgrade_paid.balance_due, 0)
            self.assertEqual(
                [entry.provider_reference for entry in upgrade_paid.payment_transactions],
                ["UPI-TEST-001", "BANK-UPGRADE-001"],
            )
            transactions = list(
                db.scalars(
                    select(PaymentTransaction)
                    .where(PaymentTransaction.booking_id == original.id)
                    .order_by(PaymentTransaction.id)
                )
            )
            self.assertEqual(
                [(entry.transaction_type, entry.amount) for entry in transactions],
                [
                    (PaymentTransactionType.PAYMENT, 2000),
                    (PaymentTransactionType.PAYMENT, 1000),
                ],
            )

            cancelled = admin_cancel_booking(original.id, db)
            reopened, _ = service.check_availability(
                AvailabilityRequest(
                    space_id="premium_large",
                    booking_date=booking_date,
                    start_time=time(12, 30),
                    duration_hours=2,
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
            self.assertEqual(refunded.amount_paid, 0)
            self.assertEqual(
                [entry.transaction_type for entry in refunded.payment_transactions],
                ["payment", "payment", "refund"],
            )

            with self.assertRaises(HTTPException) as duplicate_cancel:
                admin_cancel_booking(original.id, db)
            self.assertEqual(duplicate_cancel.exception.status_code, 409)

            unpaid_cancelled = admin_cancel_booking(second.id, db)
            self.assertEqual(unpaid_cancelled.payment_status, "void")

    def test_admin_can_create_past_current_and_future_offline_bookings(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        studio_today = datetime.now(ZoneInfo(settings.studio_timezone)).date()

        with Session(engine) as db:
            created = []
            for booking_date, start_time, amount, email in (
                (studio_today - timedelta(days=30), time(9), 1750, "past@example.com"),
                (studio_today, time(12), 2000, "today@example.com"),
                (studio_today + timedelta(days=30), time(15), 2250, "future@example.com"),
            ):
                created.append(
                    admin_create_offline_booking(
                        AdminOfflineBookingCreate(
                            space_id="standard_small",
                            booking_date=booking_date,
                            start_time=start_time,
                            duration_hours=2,
                            customer_name="Offline Customer",
                            customer_email=email,
                            phone_number="+919999999999",
                            purpose="Fashion Shoot",
                            total_amount=amount,
                            payment_method="upi" if email == "past@example.com" else None,
                            terms_accepted=True,
                        ),
                        db,
                    )
                )

            self.assertEqual([item.status for item in created], ["confirmed"] * 3)
            self.assertEqual([item.payment_status for item in created], ["pending"] * 3)
            self.assertEqual([item.total_amount for item in created], [1750, 2000, 2250])
            self.assertEqual([item.payment_mode for item in created], ["pay_at_studio"] * 3)
            self.assertEqual([item.terms_accepted for item in created], ["v2"] * 3)
            self.assertEqual([item.payment_method for item in created], ["upi", None, None])
            self.assertTrue(db.get(Booking, created[0].id).calendar_event_id.startswith("gcal_stub_"))
            self.assertTrue(db.get(Booking, created[1].id).calendar_event_id.startswith("gcal_stub_"))
            self.assertTrue(db.get(Booking, created[2].id).calendar_event_id.startswith("gcal_stub_"))

            manually_paid = admin_update_payment(
                created[1].id,
                AdminPaymentUpdate(
                    status="paid",
                    provider_reference="CASH-OFFLINE-001",
                    payment_method="cash",
                ),
                db,
            )
            self.assertEqual(manually_paid.payment_status, "paid")

            payment = db.scalar(
                select(PaymentRecord).where(PaymentRecord.booking_id == created[0].id)
            )
            self.assertIsNotNone(payment)
            self.assertEqual(payment.status, PaymentStatus.PENDING)
            self.assertEqual(payment.amount, 1750)

            past_moved = admin_update_booking(
                created[0].id,
                AdminBookingUpdate(
                    space_id="premium_large",
                    booking_date=studio_today - timedelta(days=30),
                    start_time=time(9),
                    duration_hours=2,
                    customer_name="Offline Customer",
                    customer_email="past@example.com",
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                ),
                db,
            )
            self.assertEqual(past_moved.space_id, "premium_large")
            self.assertEqual(past_moved.total_amount, 3000)

            with self.assertRaises(HTTPException) as downgrade:
                admin_update_booking(
                    created[0].id,
                    AdminBookingUpdate(
                        space_id="standard_small",
                        booking_date=studio_today - timedelta(days=30),
                        start_time=time(9),
                        duration_hours=2,
                        customer_name="Offline Customer",
                        customer_email="past@example.com",
                        phone_number="+919999999999",
                        purpose="Fashion Shoot",
                    ),
                    db,
                )
            self.assertEqual(downgrade.exception.status_code, 409)
            self.assertIn("downgrades are not allowed", downgrade.exception.detail)
            db.refresh(payment)
            self.assertEqual(db.get(Booking, created[0].id).space_id, "premium_large")
            self.assertEqual(payment.amount, 3000)

            rescheduled = admin_update_booking(
                created[2].id,
                AdminBookingUpdate(
                    space_id="standard_small",
                    booking_date=studio_today + timedelta(days=30),
                    start_time=time(17),
                    duration_hours=2,
                    customer_name="Offline Customer",
                    customer_email="future@example.com",
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                ),
                db,
            )
            self.assertEqual(rescheduled.start_time, "17:00")
            self.assertEqual(rescheduled.total_amount, 2250)
            future_payment = db.scalar(
                select(PaymentRecord).where(PaymentRecord.booking_id == created[2].id)
            )

            arena_conflict = admin_create_offline_booking(
                AdminOfflineBookingCreate(
                    space_id="premium_large",
                    booking_date=studio_today + timedelta(days=30),
                    start_time=time(17),
                    duration_hours=2,
                    customer_name="Arena Customer",
                    customer_email="arena@example.com",
                    phone_number="+917777777777",
                    purpose="Fashion Shoot",
                    total_amount=3000,
                    terms_accepted=True,
                ),
                db,
            )
            with self.assertRaises(HTTPException) as unavailable_studio:
                admin_update_booking(
                    created[2].id,
                    AdminBookingUpdate(
                        space_id="premium_large",
                        booking_date=studio_today + timedelta(days=30),
                        start_time=time(17),
                        duration_hours=2,
                        customer_name="Offline Customer",
                        customer_email="future@example.com",
                        phone_number="+919999999999",
                        purpose="Fashion Shoot",
                    ),
                    db,
                )
            self.assertEqual(unavailable_studio.exception.status_code, 409)
            unchanged = db.get(Booking, created[2].id)
            unchanged_payment = db.scalar(
                select(PaymentRecord).where(PaymentRecord.booking_id == created[2].id)
            )
            self.assertEqual(unchanged.space_id, "standard_small")
            self.assertEqual(unchanged_payment.amount, 2250)

            admin_cancel_booking(arena_conflict.id, db)
            moved = admin_update_booking(
                created[2].id,
                AdminBookingUpdate(
                    space_id="premium_large",
                    booking_date=studio_today + timedelta(days=30),
                    start_time=time(17),
                    duration_hours=2,
                    customer_name="Offline Customer",
                    customer_email="future@example.com",
                    phone_number="+919999999999",
                    purpose="Fashion Shoot",
                ),
                db,
            )
            self.assertEqual(moved.space_id, "premium_large")
            self.assertEqual(moved.total_amount, 3000)
            db.refresh(future_payment)
            self.assertEqual(future_payment.amount, 3000)

            paid = admin_update_payment(
                created[0].id,
                AdminPaymentUpdate(
                    status="paid",
                    provider_reference="UPI-OFFLINE-001",
                    payment_method="upi",
                ),
                db,
            )
            self.assertEqual(paid.payment_status, "paid")
            self.assertEqual(paid.payment_reference, "UPI-OFFLINE-001")
            self.assertEqual(paid.payment_method, "upi")
            self.assertEqual(paid.total_amount, 3000)

            with self.assertRaises(HTTPException) as conflict:
                admin_create_offline_booking(
                    AdminOfflineBookingCreate(
                        space_id="standard_small",
                        booking_date=studio_today,
                        start_time=time(12, 30),
                        duration_hours=2,
                        customer_name="Conflicting Customer",
                        customer_email="conflict@example.com",
                        phone_number="+918888888888",
                        purpose="Fashion Shoot",
                        total_amount=2000,
                        terms_accepted=True,
                    ),
                    db,
                )
            self.assertEqual(conflict.exception.status_code, 409)

    def test_booking_directory_sorts_by_scheduled_date_and_time_descending(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            bookings = [
                Booking(
                    phone_number="+919999999901",
                    state=BookingState.CONFIRMED,
                    space_id="standard_small",
                    booking_date="2026-09-24",
                    start_time="18:00",
                    duration_hours=1,
                    customer_name="Older session",
                    created_at=datetime(2026, 9, 26, 12),
                ),
                Booking(
                    phone_number="+919999999902",
                    state=BookingState.CONFIRMED,
                    space_id="standard_small",
                    booking_date="2026-09-26",
                    start_time="09:00",
                    duration_hours=1,
                    customer_name="Latest day morning",
                    created_at=datetime(2026, 9, 24, 12),
                ),
                Booking(
                    phone_number="+919999999903",
                    state=BookingState.CONFIRMED,
                    space_id="standard_small",
                    booking_date="2026-09-26",
                    start_time="17:00",
                    duration_hours=1,
                    customer_name="Latest day evening",
                    created_at=datetime(2026, 9, 23, 12),
                ),
                Booking(
                    phone_number="+919999999904",
                    state=BookingState.SELECT_SPACE,
                    customer_name="Unscheduled",
                    created_at=datetime(2026, 9, 27, 12),
                ),
            ]
            db.add_all(bookings)
            db.commit()

            rows = admin_bookings(
                space_id=None,
                q=None,
                booking_status=None,
                date_from=None,
                date_to=None,
                limit=200,
                db=db,
            )

            self.assertEqual(
                [row.customer_name for row in rows],
                [
                    "Latest day evening",
                    "Latest day morning",
                    "Older session",
                    "Unscheduled",
                ],
            )

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
                        duration_hours=2,
                        customer_name=customer_name,
                        customer_email=email,
                        phone_number="+919999999999",
                        purpose="Product Shoot",
                        terms_accepted=True,
                        payment_mode="pay_now",
                    )
                )

            service.create_booking(
                WebBookingCreate(
                    space_id="premium_large",
                    booking_date=first_date,
                    start_time=time(11),
                    duration_hours=2,
                    customer_name="Other Studio Customer",
                    customer_email="other@example.com",
                    phone_number="+918888888888",
                    purpose="Fashion Shoot",
                    terms_accepted=True,
                    payment_mode="pay_now",
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
            self.assertEqual(rows[0][12], "Payment flow")
            self.assertEqual(rows[0][13], "Payment method")
            self.assertEqual(rows[1][14], "2000")
            self.assertIn("attachment", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
