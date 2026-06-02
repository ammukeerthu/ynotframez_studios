from app.core.config import settings
from app.models.booking import Booking
from app.services.spaces import get_space_by_id


class EmailService:
    """Stub for email confirmations."""

    def send_booking_confirmation(self, booking: Booking) -> None:
        space = get_space_by_id(booking.space_id)
        print(
            "Email confirmation stub sent:",
            {
                "to": booking.customer_email,
                "from": settings.studio_email,
                "subject": "Studio booking confirmation",
                "space": space.name if space else booking.space_id,
                "date": booking.booking_date,
                "time": booking.start_time,
                "duration_hours": booking.duration_hours,
                "payment_mode": booking.payment_mode,
                "payment_link": booking.payment_link,
            },
        )

