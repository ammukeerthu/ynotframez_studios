from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking
from app.services.spaces import get_space_by_id


class RazorpayError(RuntimeError):
    pass


@dataclass(frozen=True)
class RazorpayPaymentLink:
    id: str
    url: str


@dataclass(frozen=True)
class RazorpayOrder:
    id: str
    key_id: str
    amount: int
    currency: str


class RazorpayService:
    """Create Razorpay orders/links and validate Razorpay signatures."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def _require_api_credentials(self) -> None:
        mode = settings.razorpay_mode.strip().lower()
        if mode not in {"stub", "api"}:
            raise RazorpayError("RAZORPAY_MODE must be 'stub' or 'api'.")
        if mode == "api" and (
            not settings.razorpay_key_id.strip() or not settings.razorpay_key_secret.strip()
        ):
            raise RazorpayError("Razorpay API credentials are not configured.")

    def create_order(self, booking: Booking, amount_rupees: int) -> RazorpayOrder:
        """Create the server-owned order used by Razorpay Standard Checkout."""
        self._require_api_credentials()
        amount_paise = int(amount_rupees) * 100
        if amount_paise < 100:
            raise RazorpayError("Razorpay orders must be at least 100 paise.")
        if settings.razorpay_mode.strip().lower() == "stub":
            return RazorpayOrder(
                id=f"order_stub_{booking.id}",
                key_id="",
                amount=amount_paise,
                currency="INR",
            )

        reference = f"YNF-{booking.id:06d}"
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": reference,
            "notes": {
                "booking_id": str(booking.id),
                "booking_reference": reference,
                "space_id": booking.space_id or "",
            },
        }
        try:
            response = requests.post(
                f"{settings.razorpay_api_base_url.rstrip('/')}/orders",
                auth=(settings.razorpay_key_id.strip(), settings.razorpay_key_secret.strip()),
                json=payload,
                timeout=settings.razorpay_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise RazorpayError(f"Razorpay could not create the checkout order: {error}") from error
        if not data.get("id"):
            raise RazorpayError("Razorpay returned an incomplete order response.")
        if int(data.get("amount", 0)) != amount_paise or data.get("currency") != "INR":
            raise RazorpayError("Razorpay returned unexpected order details.")
        return RazorpayOrder(
            id=data["id"],
            key_id=settings.razorpay_key_id.strip(),
            amount=amount_paise,
            currency="INR",
        )

    def create_payment_link(self, booking: Booking) -> RazorpayPaymentLink:
        """Retain hosted Payment Links for the provider-neutral WhatsApp flow."""
        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        amount = int(round((space.hourly_rate if space else 0) * (booking.duration_hours or 1)))
        if settings.razorpay_mode.strip().lower() == "stub":
            return RazorpayPaymentLink(
                id=f"plink_stub_{booking.id}",
                url=f"{settings.razorpay_payment_link_base_url}?booking_id={booking.id}&amount={amount}",
            )
        self._require_api_credentials()

        reference = f"YNF-{booking.id:06d}"
        payload: dict = {
            "amount": amount * 100,
            "currency": "INR",
            "accept_partial": False,
            "expire_by": int(
                (datetime.now(UTC) + timedelta(minutes=settings.razorpay_payment_hold_minutes)).timestamp()
            ),
            "reference_id": reference,
            "description": f"{space.name if space else 'Studio'} booking {reference}",
            "customer": {
                "name": booking.customer_name or "Customer",
                "contact": booking.phone_number,
                "email": booking.customer_email or "",
            },
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {"booking_id": str(booking.id), "booking_reference": reference},
        }
        callback_base = settings.razorpay_callback_base_url.strip().rstrip("/")
        if callback_base:
            payload.update(
                {
                    "callback_url": f"{callback_base}/payment/return/{reference}",
                    "callback_method": "get",
                }
            )
        try:
            response = requests.post(
                f"{settings.razorpay_api_base_url.rstrip('/')}/payment_links",
                auth=(settings.razorpay_key_id.strip(), settings.razorpay_key_secret.strip()),
                json=payload,
                timeout=settings.razorpay_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise RazorpayError(f"Razorpay could not create the payment link: {error}") from error
        if not data.get("id") or not data.get("short_url"):
            raise RazorpayError("Razorpay returned an incomplete payment-link response.")
        return RazorpayPaymentLink(id=data["id"], url=data["short_url"])

    @staticmethod
    def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
        secret = settings.razorpay_key_secret.encode("utf-8")
        if not secret or not order_id or not payment_id or not signature:
            return False
        expected = hmac.new(secret, f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def fetch_payment(self, payment_id: str) -> dict:
        self._require_api_credentials()
        if settings.razorpay_mode.strip().lower() == "stub":
            return {
                "id": payment_id,
                "order_id": payment_id.replace("pay_stub_", "order_stub_"),
                "amount": 0,
                "currency": "INR",
                "status": "captured",
            }
        try:
            response = requests.get(
                f"{settings.razorpay_api_base_url.rstrip('/')}/payments/{payment_id}",
                auth=(settings.razorpay_key_id.strip(), settings.razorpay_key_secret.strip()),
                timeout=settings.razorpay_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise RazorpayError(f"Razorpay could not verify the payment status: {error}") from error
        if not isinstance(data, dict) or not data.get("id"):
            raise RazorpayError("Razorpay returned an incomplete payment response.")
        return data

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> bool:
        secret = settings.razorpay_webhook_secret.encode("utf-8")
        if not secret or not signature:
            return False
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

