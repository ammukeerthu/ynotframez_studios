"""Verify read/write/delete access to each configured studio calendar."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.models.booking import Booking
from app.services.calendar_service import GoogleCalendarService


STUDIOS = (
    ("standard_small", "Standard Studio"),
    ("premium_large", "Premium Studio"),
)


def verify_calendar(calendar: GoogleCalendarService, space_id: str, studio_name: str) -> None:
    calendar_id = calendar._calendar_id_for_space(space_id)
    metadata = calendar.service.calendars().get(calendarId=calendar_id).execute()
    test_day = datetime.now(ZoneInfo(settings.studio_timezone)).date() + timedelta(days=30)
    booking = Booking(
        id=0,
        phone_number="calendar-test",
        space_id=space_id,
        booking_date=test_day.isoformat(),
        start_time=time(6).strftime("%H:%M"),
        duration_hours=0.5,
        customer_name="Calendar integration test",
        customer_email="no-email@example.invalid",
        purpose="Temporary connectivity check",
    )

    event_id = calendar.create_event(booking)
    try:
        event = calendar.service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        if event.get("id") != event_id:
            raise RuntimeError(f"Google returned an unexpected event for {studio_name}.")
    finally:
        calendar.delete_event(event_id, space_id)

    print(f"PASS | {studio_name} | Google calendar: {metadata.get('summary', '<unnamed>')} | test event removed")


def main() -> None:
    if settings.calendar_mode.strip().lower() != "google":
        raise RuntimeError("CALENDAR_MODE must be 'google' before running this verification.")

    calendar = GoogleCalendarService()
    for space_id, studio_name in STUDIOS:
        verify_calendar(calendar, space_id, studio_name)


if __name__ == "__main__":
    main()
