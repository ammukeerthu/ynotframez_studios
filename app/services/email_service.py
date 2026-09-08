import html
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking, PaymentMode
from app.models.payment import PaymentRecord
from app.services.spaces import get_space_by_id


class EmailService:
    """Build and deliver customer booking emails through console or SMTP mode."""

    logo_path = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "brand"
        / "ynotframez-logo-email.png"
    )

    subjects = {
        "confirmation": "Booking confirmed",
        "update": "Booking updated",
        "cancellation": "Booking cancelled",
        "payment_hold": "Booking request received — payment pending",
        "payment_failure": "Payment action required",
    }

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def send_booking_confirmation(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "confirmation")

    def send_booking_updated(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "update")

    def send_booking_cancelled(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "cancellation")

    def send_payment_hold(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "payment_hold")

    def send_payment_failed(self, booking: Booking) -> bool:
        return self._send_booking_message(booking, "payment_failure")

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
        subject = (
            f"Booking confirmation for {details['customer_name']}"
            if message_type == "confirmation"
            else f"Rescheduled booking confirmation for {details['customer_name']}"
            if message_type == "update"
            else f"Booking cancellation for {details['customer_name']}"
            if message_type == "cancellation"
            else f"Booking request received — payment pending ({details['reference']})"
            if message_type == "payment_hold"
            else f"Payment action required for {details['customer_name']}"
        )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((settings.email_from_name, settings.studio_email))
        message["To"] = booking.customer_email or ""
        if settings.email_reply_to.strip():
            message["Reply-To"] = settings.email_reply_to.strip()
        try:
            logo_bytes = self.logo_path.read_bytes()
        except OSError:
            logo_bytes = None
        logo_content_id = make_msgid(domain="ynotframezstudios.com") if logo_bytes else None

        message.set_content(self._plain_body(details, message_type))
        message.add_alternative(
            self._html_body(
                details,
                message_type,
                logo_content_id[1:-1] if logo_content_id else None,
            ),
            subtype="html",
        )
        if logo_bytes and logo_content_id:
            html_part = message.get_payload()[-1]
            html_part.add_related(
                logo_bytes,
                maintype="image",
                subtype="png",
                cid=logo_content_id,
                filename="ynotframez-studios-white.png",
                disposition="inline",
            )
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
        hold_started_at = booking.updated_at or booking.created_at or datetime.now(UTC)
        if hold_started_at.tzinfo is None:
            hold_started_at = hold_started_at.replace(tzinfo=ZoneInfo("UTC"))
        hold_expires_at = (
            hold_started_at + timedelta(minutes=settings.razorpay_payment_hold_minutes)
        ).astimezone(ZoneInfo(settings.studio_timezone))
        callback_base = settings.razorpay_callback_base_url.strip().rstrip("/")
        booking_url = (
            f"{callback_base}/my-booking?reference={quote(self._reference(booking))}"
            if callback_base
            else ""
        )
        return {
            "reference": self._reference(booking),
            "customer_name": booking.customer_name or "Customer",
            "space_name": space.name if space else booking.space_id or "Studio space",
            "date": start.strftime("%A, %d %B %Y") if start else booking.booking_date or "To be confirmed",
            "time": (
                f"{start.strftime('%I:%M %p').lstrip('0')} to {end.strftime('%I:%M %p').lstrip('0')}"
                if start and end else booking.start_time or "To be confirmed"
            ),
            "duration": f"{duration:g} hour{'s' if duration != 1 else ''}",
            "purpose": booking.purpose or "Not provided",
            "rules": space.rules if space else "Please contact the studio team for the applicable studio rules.",
            "payment_mode": "Pay now" if payment_mode == PaymentMode.PAY_NOW.value else "Pay at studio",
            "amount": f"₹{amount:,.0f}",
            "payment_link": booking.payment_link or "",
            "booking_url": booking_url,
            "hold_expires_at": hold_expires_at.strftime("%d %B %Y at %I:%M %p %Z").lstrip("0"),
            "studio_email": settings.studio_email,
            "payment_failed": (
                "yes"
                if payment_mode == PaymentMode.PAY_AT_STUDIO.value and not booking.payment_link
                else ""
            ),
        }

    def _plain_body(self, details: dict[str, str], message_type: str) -> str:
        introductions = {
            "confirmation": "Your booking has been scheduled.",
            "update": "Your booking has been rescheduled.",
            "cancellation": "Your booking has been cancelled.",
            "payment_hold": "We received your booking request.",
            "payment_failure": "Your payment could not be completed.",
        }
        salutations = {
            "confirmation": "Dear",
            "update": "Dear",
            "cancellation": "Dear",
            "payment_hold": "Dear",
            "payment_failure": "Dear",
        }
        payment_line = ""
        if message_type != "cancellation" and details["payment_link"]:
            payment_line = f"\nPayment link: {details['payment_link']}"
        payment_failure_line = ""
        if message_type == "payment_failure" or (
            message_type != "cancellation" and details["payment_failed"]
        ):
            payment_failure_line = (
                f"\n\nImportant: Your payment of {details['amount']} has failed. "
                "Kindly contact the studio team to reserve your booking; otherwise, "
                "we may unblock the booking if payment remains unresolved for more than two hours."
            )
        payment_hold_line = ""
        if message_type == "payment_hold":
            payment_hold_line = (
                "\n\nPayment pending — your booking is not confirmed yet. "
                f"We are temporarily holding this studio time until {details['hold_expires_at']}. "
                "Complete payment within this period to confirm the booking. If payment is not "
                "completed, the hold will expire automatically and the time will become available "
                "to others. If Razorpay has a technical issue, retry from Find My Booking or "
                f"contact the studio at {details['studio_email']} before the hold expires."
            )
            if details["booking_url"]:
                payment_hold_line += f"\nFind My Booking: {details['booking_url']}"
        rules_section = ""
        if message_type != "cancellation":
            rules_section = f"\n\nStudio rules:\n{details['rules']}"
        return (
            f"YNotFramez Studios\n\n"
            f"{salutations[message_type]} {details['customer_name']},\n\n"
            f"{introductions[message_type]}\n\n"
            f"Reference: {details['reference']}\n"
            f"Studio: {details['space_name']}\n"
            f"Date: {details['date']}\n"
            f"Time: {details['time']}\n"
            f"Duration: {details['duration']}\n"
            f"Purpose: {details['purpose']}\n"
            f"Amount: {details['amount']}"
            f"{payment_line}\n\n"
            f"{payment_failure_line}\n"
            f"{payment_hold_line}\n"
            f"{rules_section}\n\n"
            f"Please keep your booking reference for future lookup.\n\n"
            f"YNotFramez Studios"
        )

    def _html_body(
        self,
        details: dict[str, str],
        message_type: str,
        logo_content_id: str | None = None,
    ) -> str:
        introductions = {
            "confirmation": "Your booking has been scheduled.",
            "update": "Your booking has been rescheduled.",
            "cancellation": "Your booking has been cancelled.",
            "payment_hold": "We received your booking request.",
            "payment_failure": "Your payment could not be completed.",
        }
        salutations = {
            "confirmation": "Dear",
            "update": "Dear",
            "cancellation": "Dear",
            "payment_hold": "Dear",
            "payment_failure": "Dear",
        }
        escaped = {key: html.escape(value) for key, value in details.items()}
        brand_header = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            'border="0" bgcolor="#FFFFFF" style="width:100%;background-color:#FFFFFF!important">'
            '<tr><td bgcolor="#FFFFFF" '
            'style="padding:22px 28px;background-color:#FFFFFF!important">'
            f'<img src="cid:{logo_content_id}" width="300" alt="YNotFramez Studios" '
            'style="display:block;width:300px;max-width:100%;height:auto;border:0;'
            'background-color:#FFFFFF!important;color:#111111">'
            "</td></tr></table>"
            if logo_content_id
            else (
                '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
                'border="0" bgcolor="#FFFFFF" style="width:100%;background-color:#FFFFFF!important">'
                '<tr><td bgcolor="#FFFFFF" style="padding:22px 28px;background-color:#FFFFFF!important;'
                'color:#111111;font:700 15px Arial;letter-spacing:.12em">'
                "YNotFramez Studios</td></tr></table>"
            )
        )
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
        if message_type == "payment_hold" and details["booking_url"]:
            payment_button = (
                '<p style="margin:28px 0"><a href="' + escaped["booking_url"] + '" '
                'style="display:inline-block;padding:14px 22px;background:#ff5b35;color:#fff;'
                'text-decoration:none;font:700 12px Arial;letter-spacing:.08em">'
                'VIEW BOOKING &amp; COMPLETE PAYMENT</a></p>'
            )
        payment_failure_notice = ""
        if message_type == "payment_failure" or (
            message_type != "cancellation" and details["payment_failed"]
        ):
            payment_failure_notice = (
                '<div style="margin-top:28px;padding:18px 20px;background:#fdeaea;'
                'border-left:4px solid #c62828;color:#8f1d1d">'
                '<p style="margin:0;font:700 13px/1.7 Arial">Your payment of '
                + escaped["amount"]
                + " has failed. Kindly contact the studio team to reserve your booking; otherwise, "
                "we may unblock the booking if payment remains unresolved for more than two hours.</p></div>"
            )
        payment_hold_notice = ""
        if message_type == "payment_hold":
            payment_hold_notice = (
                '<div style="margin-top:28px;padding:18px 20px;background:#fff4df;'
                'border-left:4px solid #d78316;color:#67430f">'
                '<p style="margin:0 0 8px;font:700 13px/1.7 Arial">Payment pending — this is '
                'not a confirmed booking.</p>'
                '<p style="margin:0;font:13px/1.7 Arial">We are temporarily holding this studio '
                'time until <strong>' + escaped["hold_expires_at"] + '</strong>. Complete payment '
                'within this period to confirm it. If payment is not completed, the hold will expire '
                'automatically and the time will become available to others. If Razorpay has a '
                'technical issue, retry from Find My Booking or contact the studio at '
                '<a href="mailto:' + escaped["studio_email"] + '" style="color:#67430f">'
                + escaped["studio_email"] + '</a> before the hold expires.</p></div>'
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
                ("Amount", "amount"),
            )
        )
        return f"""<!doctype html>
<html>
<head>
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light only">
</head>
<body style="margin:0;background:#f5f3ed;background-color:#f5f3ed;color:#111;color-scheme:light only">
  <div style="max-width:620px;margin:0 auto;padding:38px 20px">
    {brand_header}
    <div style="padding:28px;background:#111;color:#fff">
      <div style="color:#aaa;font:8px Arial;letter-spacing:.3em">AVADI</div>
      <h1 style="margin:30px 0 0;font:38px Georgia">{introductions[message_type]}</h1>
    </div>
    <div style="padding:30px;background:#fff">
      <p style="margin:0 0 24px;font:17px Georgia">{salutations[message_type]} {escaped['customer_name']},</p>
      <table style="width:100%;border-collapse:collapse;border-top:1px solid #ddd;border-bottom:1px solid #ddd">{rows}</table>
      {payment_button}
      {payment_hold_notice}
      {payment_failure_notice}
      {rules_section}
      <p style="margin:25px 0 0;color:#777;font:12px/1.6 Arial">Keep your reference private. You can retrieve this booking from the Find My Booking page.</p>
    </div>
  </div>
</body></html>"""

    @staticmethod
    def _reference(booking: Booking) -> str:
        return f"YNF-{booking.id:06d}" if booking.id is not None else "YNF-PENDING"
