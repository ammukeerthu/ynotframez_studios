from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.availability import AvailabilityBlock
from app.services.calendar_service import GoogleCalendarService


@dataclass(frozen=True)
class AvailabilityBlockSyncResult:
    linked: int = 0
    created: int = 0
    failed: int = 0


def sync_missing_availability_block_events(db: Session) -> AvailabilityBlockSyncResult:
    """Link every legacy DB-only block to one idempotent Google Calendar event."""
    if settings.calendar_mode.strip().lower() != "google":
        return AvailabilityBlockSyncResult()

    calendar = GoogleCalendarService(db)
    blocks = list(
        db.scalars(
            select(AvailabilityBlock)
            .where(
                or_(
                    AvailabilityBlock.calendar_event_id.is_(None),
                    AvailabilityBlock.calendar_event_id.like("gcal_stub_%"),
                )
            )
            .order_by(
                AvailabilityBlock.booking_date,
                AvailabilityBlock.start_time,
                AvailabilityBlock.id,
            )
        )
    )
    linked = 0
    created = 0
    failed = 0
    for block in blocks:
        created_event_id: str | None = None
        event_was_created = False
        try:
            event_id = calendar.find_availability_block_event(block)
            if event_id is None:
                event_id = calendar.create_availability_block_event(block)
                created_event_id = event_id
                event_was_created = True
            block.calendar_event_id = event_id
            db.commit()
            if event_was_created:
                created += 1
            else:
                linked += 1
        except Exception as error:
            db.rollback()
            if created_event_id:
                try:
                    calendar.delete_event(created_event_id, block.space_id)
                except Exception as cleanup_error:
                    print(
                        "Availability block calendar cleanup failed:",
                        {"block_id": block.id, "error": str(cleanup_error)},
                    )
            failed += 1
            print(
                "Availability block calendar sync failed:",
                {"block_id": block.id, "error": f"{type(error).__name__}: {error}"},
            )
    return AvailabilityBlockSyncResult(linked=linked, created=created, failed=failed)
