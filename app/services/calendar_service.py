from datetime import datetime, timedelta
from uuid import uuid4

from app.models.booking import Booking
from app.services.spaces import get_space_by_id


class GoogleCalendarService:
    """Stub for Google Calendar availability and event sync."""

    def is_available(self, booking: Booking) -> bool:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            return False

        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)

        business_start = start.replace(hour=9, minute=0)
        business_end = start.replace(hour=20, minute=0)
        return business_start <= start and end <= business_end

    def create_event(self, booking: Booking) -> str:
        space = get_space_by_id(booking.space_id)
        space_name = space.name if space else "Studio Space"
        event_id = f"gcal_stub_{uuid4().hex[:12]}"
        print(
            "Google Calendar event stub created:",
            {
                "event_id": event_id,
                "summary": f"{space_name} booking for {booking.customer_name}",
                "date": booking.booking_date,
                "start_time": booking.start_time,
                "duration_hours": booking.duration_hours,
            },
        )
        return event_id

    def _start_datetime(self, booking: Booking) -> datetime:
        return datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")

