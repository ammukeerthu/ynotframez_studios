import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.availability import AvailabilityBlock
from app.services.availability_block_sync import sync_missing_availability_block_events


class AvailabilityBlockSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_calendar_mode = settings.calendar_mode
        settings.calendar_mode = "google"

    def tearDown(self) -> None:
        settings.calendar_mode = self.original_calendar_mode

    def test_missing_block_event_is_created_and_not_duplicated(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            block = AvailabilityBlock(
                space_id="standard_small",
                booking_date=(date.today() + timedelta(days=1)).isoformat(),
                start_time="14:30",
                duration_hours=1,
                reason="Maintenance",
            )
            db.add(block)
            db.commit()

            with patch(
                "app.services.availability_block_sync.GoogleCalendarService"
            ) as calendar_factory:
                calendar = calendar_factory.return_value
                calendar.find_availability_block_event.return_value = None
                calendar.create_availability_block_event.return_value = "google-block-event"

                first = sync_missing_availability_block_events(db)
                second = sync_missing_availability_block_events(db)

            saved = db.scalar(select(AvailabilityBlock))
            self.assertEqual(saved.calendar_event_id, "google-block-event")
            self.assertEqual((first.created, first.linked, first.failed), (1, 0, 0))
            self.assertEqual((second.created, second.linked, second.failed), (0, 0, 0))
            calendar.create_availability_block_event.assert_called_once()


if __name__ == "__main__":
    unittest.main()
