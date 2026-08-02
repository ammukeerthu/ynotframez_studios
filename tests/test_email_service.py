import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.models.booking import Booking, PaymentMode
from app.services.email_service import EmailService


class EmailServiceTest(unittest.TestCase):
    def booking(self) -> Booking:
        return Booking(
            id=42,
            phone_number="+919999999999",
            space_id="standard_small",
            booking_date="2026-09-01",
            start_time="14:30",
            duration_hours=1.5,
            customer_name="Email Customer",
            customer_email="customer@example.com",
            purpose="Portrait session",
            payment_mode=PaymentMode.PAY_NOW,
            payment_link="https://payments.example/booking-42",
        )

    def test_confirmation_contains_plain_and_html_booking_details(self) -> None:
        message = EmailService()._build_message(self.booking(), "confirmation")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        self.assertEqual(message["To"], "customer@example.com")
        self.assertIn("YNF-000042", message["Subject"])
        self.assertIn("Standard Small Space", plain)
        self.assertIn("2:30 PM – 4:00 PM", plain)
        self.assertIn("https://payments.example/booking-42", plain)
        self.assertIn("Studio rules:", plain)
        self.assertIn("arrive on time", plain.lower())
        self.assertIn("COMPLETE PAYMENT", html)
        self.assertIn("Studio rules", html)
        self.assertIn("arrive on time", html.lower())

    def test_cancellation_omits_payment_action(self) -> None:
        message = EmailService()._build_message(self.booking(), "cancellation")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        self.assertNotIn("Payment link:", plain)
        self.assertNotIn("Studio rules:", plain)
        self.assertNotIn("COMPLETE PAYMENT", html)
        self.assertNotIn("Studio rules", html)

    def test_smtp_mode_uses_starttls_login_and_multipart_message(self) -> None:
        smtp = MagicMock()
        smtp_context = smtp.return_value.__enter__.return_value
        with (
            patch.object(settings, "email_mode", "smtp"),
            patch.object(settings, "studio_email", "bookings@ynotframez.example"),
            patch.object(settings, "smtp_host", "smtp.example.com"),
            patch.object(settings, "smtp_port", 587),
            patch.object(settings, "smtp_username", "smtp-user"),
            patch.object(settings, "smtp_password", "smtp-secret"),
            patch.object(settings, "smtp_use_tls", True),
            patch.object(settings, "smtp_use_ssl", False),
            patch("app.services.email_service.smtplib.SMTP", smtp),
        ):
            delivered = EmailService().send_booking_confirmation(self.booking())

        self.assertTrue(delivered)
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=settings.smtp_timeout_seconds)
        smtp_context.starttls.assert_called_once()
        smtp_context.login.assert_called_once_with("smtp-user", "smtp-secret")
        sent_message = smtp_context.send_message.call_args.args[0]
        self.assertTrue(sent_message.is_multipart())

    def test_smtp_failure_does_not_raise_or_cancel_booking_flow(self) -> None:
        with (
            patch.object(settings, "email_mode", "smtp"),
            patch.object(settings, "smtp_host", "smtp.example.com"),
            patch.object(settings, "smtp_use_tls", True),
            patch.object(settings, "smtp_use_ssl", False),
            patch("app.services.email_service.smtplib.SMTP", side_effect=OSError("provider unavailable")),
        ):
            delivered = EmailService().send_booking_confirmation(self.booking())

        self.assertFalse(delivered)


if __name__ == "__main__":
    unittest.main()
