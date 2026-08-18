"""Refresh live Google events from confirmed SQLite booking data."""

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.booking import Booking, BookingState
from app.services.calendar_service import GoogleCalendarService
from app.services.spaces import get_space_by_id


def main() -> None:
    if settings.calendar_mode.strip().lower() != "google":
        raise RuntimeError("CALENDAR_MODE must be 'google' before refreshing live events.")

    with SessionLocal() as db:
        calendar = GoogleCalendarService(db)
        bookings = list(
            db.scalars(
                select(Booking)
                .where(or_(Booking.state == BookingState.CONFIRMED, Booking.state == BookingState.CANCELLED))
                .order_by(Booking.booking_date, Booking.start_time, Booking.id)
            )
        )
        for booking in bookings:
            if booking.state == BookingState.CANCELLED:
                booking.calendar_event_id = calendar.decline_event(booking)
                title_prefix = "DECLINED - "
            else:
                booking.calendar_event_id = calendar.update_event(booking)
                title_prefix = ""
            db.commit()
            space = get_space_by_id(booking.space_id, db, include_inactive=True)
            print(
                f"UPDATED | YNF-{booking.id:06d} | "
                f"{space.name if space else booking.space_id} | "
                f"{title_prefix}Booking - {booking.customer_name} - {booking.phone_number}"
            )

        print(f"Calendar refresh complete: {len(bookings)} booking(s).")


if __name__ == "__main__":
    main()
