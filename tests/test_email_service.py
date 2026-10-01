import unittest
from datetime import datetime
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
        email_service = EmailService()
        with patch.object(settings, "email_bcc", ""):
            message = email_service._build_message(self.booking(), "confirmation")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        self.assertEqual(message["To"], "customer@example.com")
        self.assertEqual(message["Subject"], "Booking confirmation for Email Customer")
        self.assertIn("Cube", plain)
        self.assertIn("2:30 PM to 4:00 PM", plain)
        self.assertIn("https://payments.example/booking-42", plain)
        self.assertNotIn("Payment:", plain)
        self.assertNotIn(">Payment<", html)
        self.assertIn(">Amount<", html)
        self.assertIn("Studio rules:", plain)
        self.assertIn("arrive on time", plain.lower())
        self.assertIn("COMPLETE PAYMENT", html)
        self.assertIn("YNotFramez Studios", html)
        self.assertIn('src="cid:', html)
        self.assertIn('<td align="center" bgcolor="#FFFFFF"', html)
        self.assertIn('style="display:block;margin:0 auto;width:300px;', html)
        self.assertIn('bgcolor="#FFFFFF"', html)
        self.assertIn("background-color:#FFFFFF!important", html)
        self.assertIn('content="light only"', html)
        self.assertIn("AVADI", html)
        self.assertIn("Your booking has been scheduled.", html)
        self.assertIn("Dear Email Customer,", html)
        self.assertIn("Studio rules", html)
        self.assertIn("arrive on time", html.lower())
        logo_parts = [part for part in message.walk() if part.get_content_type() == "image/png"]
        self.assertEqual(len(logo_parts), 1)
        self.assertEqual(email_service.logo_path.name, "ynotframez-logo-email.png")
        self.assertEqual(logo_parts[0].get_filename(), "ynotframez-studios-white.png")
        self.assertEqual(logo_parts[0].get_content_disposition(), "inline")
        self.assertTrue(logo_parts[0]["Content-ID"])

    def test_all_booking_messages_include_unique_internal_bcc_recipients(self) -> None:
        with patch.object(
            settings,
            "email_bcc",
            (
                "ynotframezstudios@gmail.com, dipakg160892@gmail.com; "
                "karthik2deekay@gmail.com, DIPAKG160892@gmail.com"
            ),
        ):
            for message_type in EmailService.subjects:
                with self.subTest(message_type=message_type):
                    message = EmailService()._build_message(self.booking(), message_type)
                    self.assertEqual(
                        message["Bcc"],
                        (
                            "ynotframezstudios@gmail.com, dipakg160892@gmail.com, "
                            "karthik2deekay@gmail.com"
                        ),
                    )

    def test_customer_is_not_duplicated_in_bcc(self) -> None:
        booking = self.booking()
        booking.customer_email = "DipakG160892@gmail.com"
        with patch.object(
            settings,
            "email_bcc",
            "ynotframezstudios@gmail.com,dipakg160892@gmail.com,karthik2deekay@gmail.com",
        ):
            message = EmailService()._build_message(booking, "confirmation")

        self.assertEqual(
            message["Bcc"],
            "ynotframezstudios@gmail.com, karthik2deekay@gmail.com",
        )

    def test_cancellation_omits_payment_action(self) -> None:
        message = EmailService()._build_message(self.booking(), "cancellation")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        self.assertEqual(message["Subject"], "Booking cancellation for Email Customer")
        self.assertIn("Your booking has been cancelled.", plain)
        self.assertIn("Dear Email Customer,", plain)
        self.assertIn("Your booking has been cancelled.", html)
        self.assertIn("Dear Email Customer,", html)
        self.assertNotIn("Payment link:", plain)
        self.assertNotIn("Studio rules:", plain)
        self.assertNotIn("COMPLETE PAYMENT", html)
        self.assertNotIn("Studio rules", html)

    def test_update_uses_rescheduled_customer_copy(self) -> None:
        message = EmailService()._build_message(self.booking(), "update")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        self.assertEqual(message["Subject"], "Rescheduled booking confirmation for Email Customer")
        self.assertIn("Your booking has been rescheduled.", plain)
        self.assertIn("Dear Email Customer,", plain)
        self.assertIn("Your booking has been rescheduled.", html)
        self.assertIn("Dear Email Customer,", html)

    def test_checkout_failure_is_highlighted_without_a_payment_row(self) -> None:
        booking = self.booking()
        booking.payment_mode = PaymentMode.PAY_NOW
        booking.payment_link = None

        message = EmailService()._build_message(booking, "payment_failure")
        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()

        self.assertEqual(message["Subject"], "Payment action required for Email Customer")
        self.assertIn("Your payment could not be completed.", html)
        self.assertIn("has failed", plain)
        self.assertIn("more than two hours", plain)
        self.assertIn("has failed", html)
        self.assertIn("more than two hours", html)
        self.assertIn("border-left:4px solid #c62828", html)
        self.assertNotIn(">Payment<", html)

    def test_payment_hold_email_is_clear_timed_and_actionable(self) -> None:
        booking = self.booking()
        booking.updated_at = datetime(2026, 9, 1, 10, 0)
        booking.payment_link = None
        with (
            patch.object(settings, "razorpay_callback_base_url", "https://ynotframezstudios.com"),
            patch.object(settings, "razorpay_payment_hold_minutes", 120),
            patch.object(settings, "studio_timezone", "Asia/Kolkata"),
        ):
            message = EmailService()._build_message(booking, "payment_hold")

        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertEqual(
            message["Subject"],
            "Booking request received — payment pending (YNF-000042)",
        )
        self.assertIn("your booking is not confirmed yet", plain)
        self.assertIn("1 September 2026 at 05:30 PM IST", plain)
        self.assertIn("hold will expire automatically", plain)
        self.assertIn(
            "https://ynotframezstudios.com/my-booking?reference=YNF-000042",
            plain,
        )
        self.assertIn("Payment pending — this is not a confirmed booking", html)
        self.assertIn("VIEW BOOKING &amp; COMPLETE PAYMENT", html)

    def test_expiration_email_releases_the_slot_and_invites_a_new_booking(self) -> None:
        with patch.object(
            settings,
            "razorpay_callback_base_url",
            "https://ynotframezstudios.com",
        ):
            message = EmailService()._build_message(self.booking(), "expiration")

        plain = message.get_body(preferencelist=("plain",)).get_content()
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertEqual(
            message["Subject"],
            "Booking request expired - please book again (YNF-000042)",
        )
        self.assertIn("booking was not confirmed", plain)
        self.assertIn("studio slot has been released", plain)
        self.assertIn("https://ynotframezstudios.com/book", plain)
        self.assertIn("BOOK AGAIN", html)
        self.assertIn("studio slot has been released", html)
        self.assertNotIn("COMPLETE PAYMENT", html)
        self.assertNotIn("Studio rules", html)

    def test_smtp_mode_uses_starttls_login_and_multipart_message(self) -> None:
        smtp = MagicMock()
        smtp_context = smtp.return_value.__enter__.return_value
        with (
            patch.object(settings, "email_mode", "smtp"),
            patch.object(settings, "studio_email", "bookings@ynotframez.example"),
            patch.object(settings, "email_bcc", "owner@example.com,manager@example.com"),
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
        self.assertEqual(sent_message["Bcc"], "owner@example.com, manager@example.com")

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
