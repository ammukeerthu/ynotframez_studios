import html
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking, PaymentMode
from app.models.payment import PaymentRecord
from app.services.spaces import get_space_by_id


class EmailService:
    """Build and deliver customer booking emails through console or SMTP mode."""

    subjects = {
        "confirmation": "Booking confirmed",
        "update": "Booking updated",
        "cancellation": "Booking cancelled",
    }

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def send_booking_confirmation(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "confirmation")

    def send_booking_updated(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "update")

    def send_booking_cancelled(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "cancellation")

    def _send_booking_message(self, booking: Booking, message_type: str) -> bool:
        if not booking.customer_email:
            print("Email delivery skipped: booking has no customer email address.")
            return False

        try:
            message = self._build_message(booking, message_type)
        except ValueError as error:
            print(
                "Email preparation failed; the booking remains confirmed:",
                {"to": booking.customer_email, "error": str(error)},
            )
            return False
        mode = settings.email_mode.strip().lower()
        if mode == "console":
            print(
                f"Email {message_type} prepared:",
                {
                    "to": booking.customer_email,
                    "from": settings.studio_email,
                    "subject": message["Subject"],
                    "reference": self._reference(booking),
                },
            )
            return True
        if mode != "smtp":
            print(f"Email delivery skipped: unsupported EMAIL_MODE {mode!r}.")
            return False

        try:
            self._deliver_smtp(message)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            print(
                "Email delivery failed; the booking remains confirmed:",
                {"to": booking.customer_email, "error": f"{type(error).__name__}: {error}"},
            )
            return False

        print("Email delivered:", {"to": booking.customer_email, "subject": message["Subject"]})
        return True

    def _build_message(self, booking: Booking, message_type: str) -> EmailMessage:
        if message_type not in self.subjects:
            raise ValueError(f"Unsupported booking email type: {message_type}")

        details = self._booking_details(booking)
        subject = f"{self.subjects[message_type]} · {details['reference']}"
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((settings.email_from_name, settings.studio_email))
        message["To"] = booking.customer_email or ""
        if settings.email_reply_to.strip():
            message["Reply-To"] = settings.email_reply_to.strip()
        message.set_content(self._plain_body(details, message_type))
        message.add_alternative(self._html_body(details, message_type), subtype="html")
        return message

    def _deliver_smtp(self, message: EmailMessage) -> None:
        host = settings.smtp_host.strip()
        if not host:
            raise ValueError("SMTP_HOST is required when EMAIL_MODE is smtp.")
        if settings.smtp_use_ssl and settings.smtp_use_tls:
            raise ValueError("Enable either SMTP_USE_SSL or SMTP_USE_TLS, not both.")

        context = ssl.create_default_context()
        smtp_class = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
        with smtp_class(host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as client:
            client.ehlo()
            if settings.smtp_use_tls:
                client.starttls(context=context)
                client.ehlo()
            if settings.smtp_username.strip():
                app_password = "".join(settings.smtp_password.split())
                client.login(settings.smtp_username.strip(), app_password)
            client.send_message(message)

    def _booking_details(self, booking: Booking) -> dict[str, str]:
        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        duration = booking.duration_hours or 0
        start = None
        if booking.booking_date and booking.start_time:
            start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
        end = start + timedelta(hours=duration) if start else None
        payment = (
            self.db.scalar(select(PaymentRecord).where(PaymentRecord.booking_id == booking.id))
            if self.db is not None and booking.id is not None else None
        )
        amount = payment.amount if payment else int(round((space.hourly_rate if space else 0) * duration))
        payment_mode = booking.payment_mode.value if booking.payment_mode else PaymentMode.PAY_AT_STUDIO.value
        return {
            "reference": self._reference(booking),
            "customer_name": booking.customer_name or "Customer",
            "space_name": space.name if space else booking.space_id or "Studio space",
            "date": start.strftime("%A, %d %B %Y") if start else booking.booking_date or "To be confirmed",
            "time": (
                f"{start.strftime('%I:%M %p').lstrip('0')} – {end.strftime('%I:%M %p').lstrip('0')}"
                if start and end else booking.start_time or "To be confirmed"
            ),
            "duration": f"{duration:g} hour{'s' if duration != 1 else ''}",
            "purpose": booking.purpose or "Not provided",
            "rules": space.rules if space else "Please contact the studio team for the applicable studio rules.",
            "payment_mode": "Pay now" if payment_mode == PaymentMode.PAY_NOW.value else "Pay at studio",
            "amount": f"₹{amount:,.0f}",
            "payment_link": booking.payment_link or "",
        }

    def _plain_body(self, details: dict[str, str], message_type: str) -> str:
        introductions = {
            "confirmation": "Your studio booking is confirmed.",
            "update": "Your studio booking details have been updated.",
            "cancellation": "Your studio booking has been cancelled.",
        }
        payment_line = ""
        if message_type != "cancellation" and details["payment_link"]:
            payment_line = f"\nPayment link: {details['payment_link']}"
        rules_section = ""
        if message_type != "cancellation":
            rules_section = f"\n\nStudio rules:\n{details['rules']}"
        return (
            f"YNotFramez Studios\n\n"
            f"Hi {details['customer_name']},\n\n"
            f"{introductions[message_type]}\n\n"
            f"Reference: {details['reference']}\n"
            f"Studio: {details['space_name']}\n"
            f"Date: {details['date']}\n"
            f"Time: {details['time']}\n"
            f"Duration: {details['duration']}\n"
            f"Purpose: {details['purpose']}\n"
            f"Payment: {details['payment_mode']} · {details['amount']}"
            f"{payment_line}\n\n"
            f"{rules_section}\n\n"
            f"Please keep your booking reference for future lookup.\n\n"
            f"YNotFramez Studios"
        )

    def _html_body(self, details: dict[str, str], message_type: str) -> str:
        introductions = {
            "confirmation": "Your studio is reserved.",
            "update": "Your booking has been updated.",
            "cancellation": "Your booking has been cancelled.",
        }
        escaped = {key: html.escape(value) for key, value in details.items()}
        rules_section = ""
        if message_type != "cancellation":
            rules_section = (
                '<div style="margin-top:28px;padding:20px;background:#f5f3ed;border-left:3px solid #ff5b35">'
                '<h2 style="margin:0 0 10px;font:22px Georgia">Studio rules</h2>'
                '<p style="margin:0;color:#555;font:13px/1.7 Arial">'
                + escaped["rules"].replace("\n", "<br>") + "</p></div>"
            )
        payment_button = ""
        if message_type != "cancellation" and details["payment_link"]:
            payment_button = (
                '<p style="margin:28px 0"><a href="' + escaped["payment_link"] + '" '
                'style="display:inline-block;padding:14px 22px;background:#ff5b35;color:#fff;'
                'text-decoration:none;font:700 12px Arial;letter-spacing:.08em">COMPLETE PAYMENT</a></p>'
            )
        rows = "".join(
            f'<tr><td style="padding:9px 0;color:#777;font:11px Arial;text-transform:uppercase">{label}</td>'
            f'<td style="padding:9px 0;text-align:right;color:#111;font:15px Georgia">{escaped[key]}</td></tr>'
            for label, key in (
                ("Reference", "reference"),
                ("Studio", "space_name"),
                ("Date", "date"),
                ("Time", "time"),
                ("Duration", "duration"),
                ("Purpose", "purpose"),
                ("Payment", "payment_mode"),
                ("Amount", "amount"),
            )
        )
        return f"""<!doctype html>
<html><body style="margin:0;background:#f5f3ed;color:#111">
  <div style="max-width:620px;margin:0 auto;padding:38px 20px">
    <div style="padding:28px;background:#111;color:#fff">
      <div style="font:700 15px Arial;letter-spacing:.12em">YNotFramez</div>
      <div style="margin-top:5px;color:#aaa;font:8px Arial;letter-spacing:.3em">STUDIOS</div>
      <h1 style="margin:36px 0 0;font:38px Georgia">{introductions[message_type]}</h1>
    </div>
    <div style="padding:30px;background:#fff">
      <p style="margin:0 0 24px;font:17px Georgia">Hi {escaped['customer_name']},</p>
      <table style="width:100%;border-collapse:collapse;border-top:1px solid #ddd;border-bottom:1px solid #ddd">{rows}</table>
      {payment_button}
      {rules_section}
      <p style="margin:25px 0 0;color:#777;font:12px/1.6 Arial">Keep your reference private. You can retrieve this booking from the Find My Booking page.</p>
    </div>
  </div>
</body></html>"""

    @staticmethod
    def _reference(booking: Booking) -> str:
        return f"YNF-{booking.id:06d}" if booking.id is not None else "YNF-PENDING"
