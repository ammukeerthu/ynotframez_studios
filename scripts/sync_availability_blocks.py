"""Backfill Google Calendar events for studio blocks that exist only in the database."""

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.availability_block_sync import sync_missing_availability_block_events


def main() -> None:
    if settings.calendar_mode.strip().lower() != "google":
        raise RuntimeError("CALENDAR_MODE must be 'google' before syncing availability blocks.")

    with SessionLocal() as db:
        result = sync_missing_availability_block_events(db)
    print(
        "Availability block sync complete: "
        f"{result.created} event(s) created, "
        f"{result.linked} existing event(s) linked, "
        f"{result.failed} failed."
    )
    if result.failed:
        raise RuntimeError("Some availability blocks could not be synchronized.")


if __name__ == "__main__":
    main()
