import asyncio
import hashlib
import hmac
import json
import unittest
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import admin_alerts
from app.api.routes.bookings import (
    razorpay_webhook,
    retry_booking_checkout,
    verify_razorpay_payment,
)
from app.core.config import settings
from app.core.database import Base
from app.models.booking import Booking, BookingState
from app.schemas.booking import PaymentCheckoutRequest, RazorpayPaymentVerification, WebBookingCreate
from app.services.booking_service import BookingApplicationService
from app.services.payment_service import PaymentService


class BodyRequest:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


class RazorpayCheckoutFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.booking_date = date.today() + timedelta(days=30)
        with patch.object(settings, "razorpay_mode", "stub"):
            self.created = BookingApplicationService(self.db).create_booking(
                WebBookingCreate(
                    space_id="standard_small",
                    booking_date=self.booking_date,
                    start_time=time(14, 30),
                    duration_hours=2,
                    customer_name="Checkout Customer",
                    customer_email="checkout@example.com",
                    phone_number="+919999999999",
                    purpose="Family Portraits",
                    terms_accepted=True,
                    payment_mode="pay_now",
                )
            )
        self.booking = self.db.get(Booking, self.created.id)
        self.record = PaymentService(self.db).get(self.created.id)
        self.order_id = self.record.razorpay_order_id
        self.payment_id = "pay_test_checkout"

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def verification(self, signature: str) -> RazorpayPaymentVerification:
        return RazorpayPaymentVerification(
            reference=self.created.reference,
            razorpay_order_id=self.order_id,
            razorpay_payment_id=self.payment_id,
            razorpay_signature=signature,
        )

    def signature(self, secret: str = "checkout-secret") -> str:
        return hmac.new(
            secret.encode("utf-8"),
            f"{self.order_id}|{self.payment_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def payment(self, **overrides) -> dict:
        values = {
            "id": self.payment_id,
            "order_id": self.order_id,
            "amount": self.record.amount * 100,
            "currency": "INR",
            "status": "captured",
            "method": "netbanking",
        }
        values.update(overrides)
        return values

    def test_valid_captured_payment_confirms_booking_idempotently(self) -> None:
        with (
            patch.object(settings, "razorpay_key_secret", "checkout-secret"),
            patch("app.services.razorpay_service.RazorpayService.fetch_payment", return_value=self.payment()),
        ):
            first = verify_razorpay_payment(self.verification(self.signature()), self.db)
            second = verify_razorpay_payment(self.verification(self.signature()), self.db)

        self.assertEqual(first.status, "confirmed")
        self.assertEqual(second.status, "confirmed")
        self.assertEqual(self.record.status.value, "paid")
        self.assertEqual(self.record.razorpay_payment_id, self.payment_id)
        self.assertEqual(self.record.razorpay_method, "netbanking")
        self.assertTrue((self.booking.calendar_event_id or "").startswith("gcal_stub_"))

    def test_invalid_signature_does_not_mark_payment_paid(self) -> None:
        with patch.object(settings, "razorpay_key_secret", "checkout-secret"):
            with self.assertRaises(HTTPException) as invalid:
                verify_razorpay_payment(self.verification("invalid"), self.db)

        self.assertEqual(invalid.exception.status_code, 400)
        self.assertEqual(self.record.status.value, "pending")
        self.assertEqual(self.booking.state, BookingState.PAYMENT_PENDING)

    def test_authorized_payment_waits_for_automatic_capture(self) -> None:
        with (
            patch.object(settings, "razorpay_key_secret", "checkout-secret"),
            patch(
                "app.services.razorpay_service.RazorpayService.fetch_payment",
                return_value=self.payment(status="authorized"),
            ),
        ):
            result = verify_razorpay_payment(self.verification(self.signature()), self.db)

        self.assertEqual(result.status, "payment_pending")
        self.assertEqual(self.record.status.value, "pending")
        self.assertEqual(self.record.razorpay_payment_id, self.payment_id)
        self.assertEqual(self.record.razorpay_method, "netbanking")

    def test_wrong_payment_amount_is_rejected(self) -> None:
        with (
            patch.object(settings, "razorpay_key_secret", "checkout-secret"),
            patch(
                "app.services.razorpay_service.RazorpayService.fetch_payment",
                return_value=self.payment(amount=100),
            ),
        ):
            with self.assertRaises(HTTPException) as mismatch:
                verify_razorpay_payment(self.verification(self.signature()), self.db)

        self.assertEqual(mismatch.exception.status_code, 400)
        self.assertEqual(self.record.status.value, "pending")

    def test_late_captured_payment_is_flagged_for_refund(self) -> None:
        self.booking.state = BookingState.CANCELLED
        self.db.commit()
        with (
            patch.object(settings, "razorpay_key_secret", "checkout-secret"),
            patch("app.services.razorpay_service.RazorpayService.fetch_payment", return_value=self.payment()),
        ):
            result = verify_razorpay_payment(self.verification(self.signature()), self.db)

        alerts = admin_alerts(self.db)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(self.record.status.value, "refund_due")
        self.assertEqual(self.record.razorpay_method, "netbanking")
        self.assertEqual(alerts.new_bookings[0].kind, "payment_issue")
        self.assertIn("refund", alerts.new_bookings[0].message.lower())

    def test_payment_captured_after_hold_expiry_is_flagged_for_refund(self) -> None:
        self.booking.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
        self.db.commit()
        with (
            patch.object(settings, "razorpay_key_secret", "checkout-secret"),
            patch("app.services.razorpay_service.RazorpayService.fetch_payment", return_value=self.payment()),
        ):
            result = verify_razorpay_payment(self.verification(self.signature()), self.db)

        self.assertEqual(result.status, "expired")
        self.assertEqual(self.record.status.value, "refund_due")
        self.assertIsNone(self.booking.calendar_event_id)

    def test_checkout_retry_rejects_and_expires_an_elapsed_hold(self) -> None:
        self.booking.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
        self.db.commit()

        with self.assertRaises(HTTPException) as expired:
            retry_booking_checkout(
                PaymentCheckoutRequest(
                    reference=self.created.reference,
                    customer_email=self.booking.customer_email,
                ),
                self.db,
            )

        self.assertEqual(expired.exception.status_code, 409)
        self.assertEqual(self.booking.state, BookingState.EXPIRED)
        self.assertEqual(self.record.status.value, "void")

    def test_captured_webhook_confirms_and_duplicate_is_safe(self) -> None:
        payload = {
            "event": "payment.captured",
            "payload": {
                "order": {"entity": {"id": self.order_id, "receipt": self.created.reference}},
                "payment": {"entity": self.payment()},
            },
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        webhook_secret = "webhook-secret"
        signature = hmac.new(webhook_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        with patch.object(settings, "razorpay_webhook_secret", webhook_secret):
            first = asyncio.run(razorpay_webhook(BodyRequest(raw), signature, self.db))
            second = asyncio.run(razorpay_webhook(BodyRequest(raw), signature, self.db))

        self.assertEqual(first, {"ok": True})
        self.assertEqual(second, {"ok": True})
        self.assertEqual(self.booking.state, BookingState.CONFIRMED)
        self.assertEqual(self.record.status.value, "paid")
        self.assertEqual(self.record.razorpay_method, "netbanking")

    def test_failed_webhook_keeps_checkout_retryable_without_duplicate_email(self) -> None:
        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": self.payment_id,
                        "order_id": self.order_id,
                        "notes": {"booking_id": str(self.booking.id)},
                    }
                }
            },
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        webhook_secret = "webhook-secret"
        signature = hmac.new(webhook_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        with (
            patch.object(settings, "razorpay_webhook_secret", webhook_secret),
            patch("app.services.email_service.EmailService.send_payment_failed", return_value=True) as email,
        ):
            asyncio.run(razorpay_webhook(BodyRequest(raw), signature, self.db))
            asyncio.run(razorpay_webhook(BodyRequest(raw), signature, self.db))

        self.assertEqual(self.booking.state, BookingState.PAYMENT_PENDING)
        self.assertEqual(self.record.status.value, "pending")
        self.assertEqual(self.record.provider_reference, self.payment_id)
        email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
