"""Migrate confirmed bookings with placeholder event IDs into Google Calendar."""

from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.booking import Booking, BookingState
from app.services.calendar_service import GoogleCalendarService
from app.services.spaces import get_space_by_id


def find_existing_event(calendar: GoogleCalendarService, booking: Booking) -> str | None:
    calendar_id = calendar._calendar_id_for_space(booking.space_id)
    start = calendar._start_datetime(booking)
    end = start + timedelta(hours=booking.duration_hours or 0)
    response = (
        calendar.service.events()
        .list(
            calendarId=calendar_id,
            timeMin=(start - timedelta(days=1)).isoformat(),
            timeMax=(end + timedelta(days=1)).isoformat(),
            privateExtendedProperty=f"booking_id={booking.id}",
            singleEvents=True,
        )
        .execute()
    )
    events = [event for event in response.get("items", []) if event.get("status") != "cancelled"]
    return events[0]["id"] if events else None


def main() -> None:
    if settings.calendar_mode.strip().lower() != "google":
        raise RuntimeError("CALENDAR_MODE must be 'google' before running this migration.")

    with SessionLocal() as db:
        calendar = GoogleCalendarService(db)
        bookings = list(
            db.scalars(
                select(Booking)
                .where(
                    Booking.state == BookingState.CONFIRMED,
                    Booking.calendar_event_id.like("gcal_stub_%"),
                )
                .order_by(Booking.booking_date, Booking.start_time, Booking.id)
            )
        )
        if not bookings:
            print("No confirmed stub-era bookings need migration.")
            return

        for booking in bookings:
            created_event_id: str | None = None
            live_event_id = find_existing_event(calendar, booking)
            if live_event_id is None:
                live_event_id = calendar.create_event(booking)
                created_event_id = live_event_id

            try:
                booking.calendar_event_id = live_event_id
                db.commit()
            except Exception:
                db.rollback()
                if created_event_id:
                    calendar.delete_event(created_event_id, booking.space_id)
                raise

            space = get_space_by_id(booking.space_id, db, include_inactive=True)
            studio_name = space.name if space else booking.space_id
            source = "existing event linked" if created_event_id is None else "event created"
            print(
                f"MIGRATED | YNF-{booking.id:06d} | {studio_name} | "
                f"{booking.booking_date} {booking.start_time} | {source}"
            )

        print(f"Migration complete: {len(bookings)} booking(s).")


if __name__ == "__main__":
    main()
