from app.core.config import settings
from app.models.booking import Booking
from app.services.spaces import get_space_by_id
from sqlalchemy.orm import Session


class RazorpayService:
    """Stub for Razorpay Payment Links."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def create_payment_link(self, booking: Booking) -> str:
        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        amount = int(round((space.hourly_rate if space else 0) * (booking.duration_hours or 1)))
        return f"{settings.razorpay_payment_link_base_url}?booking_id={booking.id}&amount={amount}"

