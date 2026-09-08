"""Remove booking test data and its corresponding Google Calendar events."""

from __future__ import annotations

import argparse

from googleapiclient.errors import HttpError
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.booking import Booking
from app.models.notification import AdminNotification
from app.models.payment import PaymentRecord
from app.services.calendar_service import GoogleCalendarService


def _database_label() -> str:
    if settings.database_url.startswith("sqlite"):
        return "local SQLite"
    hostname = settings.database_url.split("@", 1)[-1].split("/", 1)[0]
    return f"remote PostgreSQL ({hostname})"


def _count(db, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def clear_bookings(*, apply: bool) -> None:
    with SessionLocal() as db:
        bookings = list(db.scalars(select(Booking).order_by(Booking.id)))
        calendar_bookings = [booking for booking in bookings if booking.calendar_event_id]
        print(f"Database: {_database_label()}")
        print(f"Bookings: {len(bookings)}")
        print(f"Payment records: {_count(db, PaymentRecord)}")
        print(f"Admin notifications: {_count(db, AdminNotification)}")
        print(f"Linked calendar events: {len(calendar_bookings)}")

        if not apply:
            print("Dry run completed; nothing was deleted. Add --apply to continue.")
            return

        calendar = GoogleCalendarService(db)
        deleted_events = 0
        missing_events = 0
        for booking in calendar_bookings:
            try:
                calendar.delete_event(booking.calendar_event_id, booking.space_id)
                deleted_events += 1
            except HttpError as error:
                if getattr(error.resp, "status", None) == 404:
                    missing_events += 1
                    continue
                raise RuntimeError(
                    "Calendar cleanup failed. Database records were not deleted."
                ) from error
            except Exception as error:
                raise RuntimeError(
                    "Calendar cleanup failed. Database records were not deleted."
                ) from error

        try:
            db.execute(delete(AdminNotification))
            db.execute(delete(PaymentRecord))
            db.execute(delete(Booking))
            db.commit()
        except Exception:
            db.rollback()
            raise

        print(f"Calendar events deleted: {deleted_events}")
        if missing_events:
            print(f"Calendar events already absent: {missing_events}")
        print("Booking records, payment records, and booking notifications deleted successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all bookings and their linked Google Calendar events."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the deletion. Without this flag, only counts are shown.",
    )
    args = parser.parse_args()
    clear_bookings(apply=args.apply)


if __name__ == "__main__":
    main()
