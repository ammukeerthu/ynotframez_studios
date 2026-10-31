import unittest

from fastapi import Response
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import admin_announcement, admin_update_announcement
from app.api.routes.bookings import public_announcement
from app.core.database import Base
from app.models.announcement import AnnouncementSetting
from app.schemas.announcement import AnnouncementUpdate


class AnnouncementApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_owner_can_save_and_disable_the_public_announcement(self) -> None:
        with Session(self.engine) as db:
            default = admin_announcement(db)
            self.assertFalse(default.enabled)
            self.assertEqual(default.message, "")

            saved = admin_update_announcement(
                AnnouncementUpdate(enabled=True, category="offer", message="  Weekend offer  "),
                db,
            )
            self.assertTrue(saved.enabled)
            self.assertEqual(saved.category, "offer")
            self.assertEqual(saved.message, "Weekend offer")
            self.assertEqual(db.get(AnnouncementSetting, 1).message, "Weekend offer")

            response = Response()
            public = public_announcement(response, db)
            self.assertTrue(public.enabled)
            self.assertEqual(public.message, "Weekend offer")
            self.assertEqual(response.headers["Cache-Control"], "no-store")

            admin_update_announcement(
                AnnouncementUpdate(enabled=False, category="offer", message="Weekend offer"),
                db,
            )
            hidden = public_announcement(Response(), db)
            self.assertFalse(hidden.enabled)
            self.assertEqual(hidden.message, "")

    def test_enabled_announcement_requires_text(self) -> None:
        with self.assertRaises(ValidationError):
            AnnouncementUpdate(enabled=True, category="news", message="   ")


if __name__ == "__main__":
    unittest.main()
