import unittest
from datetime import date, time, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import admin_studios, admin_update_studio
from app.core.database import Base
from app.core.config import settings
from app.schemas.admin import AdminStudioUpdate
from app.schemas.booking import AvailabilityRequest, WebBookingCreate
from app.services.booking_service import BookingApplicationService
from app.services.spaces import get_space_by_id, list_spaces, seed_studio_settings
from app.models.studio import StudioSetting

settings.email_mode = "console"
settings.calendar_mode = "stub"


class StudioSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        seed_studio_settings(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def payload(self, **overrides) -> AdminStudioUpdate:
        values = {
            "name": "Standard Creator Space",
            "short_description": "An updated space for portraits and product work.",
            "brochure": "Updated brochure details for the standard creator studio.",
            "rules": "Arrive on time and leave the studio clean after the session.",
            "hourly_rate": 1600,
            "capacity": 6,
            "dimensions": "Compact studio · seating for 6",
            "equipment": ["Two LED lights", "Backdrop stand"],
            "amenities": ["Wi-Fi", "Changing corner"],
            "cover_image": "https://example.com/studio.jpg",
            "opening_time": "10:00",
            "closing_time": "18:00",
            "min_duration_hours": 2.0,
            "max_duration_hours": 4.0,
            "is_active": True,
            "booking_purposes": ["Portrait Session", "Product Campaign", "Workshop"],
        }
        values.update(overrides)
        return AdminStudioUpdate(**values)

    def test_owner_update_is_persisted_and_used_for_booking(self) -> None:
        updated = admin_update_studio("standard_small", self.payload(), self.db)
        spaces = admin_studios(self.db)
        stored = get_space_by_id("standard_small", self.db)

        self.assertEqual(updated.hourly_rate, 1600)
        self.assertEqual(stored.name, "Standard Creator Space")
        self.assertEqual(stored.equipment, ("Two LED lights", "Backdrop stand"))
        self.assertEqual(stored.booking_purposes, ("Portrait Session", "Product Campaign", "Workshop"))
        self.assertEqual(updated.booking_purposes, ["Portrait Session", "Product Campaign", "Workshop"])
        self.assertEqual(len(spaces), 2)

        future_date = date.today() + timedelta(days=30)
        service = BookingApplicationService(self.db)
        before_open, _ = service.check_availability(
            AvailabilityRequest(
                space_id="standard_small",
                booking_date=future_date,
                start_time=time(9, 30),
                duration_hours=2,
            )
        )
        too_short, _ = service.check_availability(
            AvailabilityRequest(
                space_id="standard_small",
                booking_date=future_date,
                start_time=time(10, 0),
                duration_hours=0.5,
            )
        )
        self.assertFalse(before_open)
        self.assertFalse(too_short)

        booking = service.create_booking(
            WebBookingCreate(
                space_id="standard_small",
                booking_date=future_date,
                start_time=time(10, 0),
                duration_hours=2,
                customer_name="Settings Customer",
                customer_email="settings@example.com",
                phone_number="+919999999999",
                purpose="Portrait Session",
                terms_accepted=True,
                payment_mode="pay_now",
            )
        )
        self.assertEqual(booking.space_name, "Standard Creator Space")
        self.assertEqual(booking.total_amount, 3200)
        self.assertIn("amount=3200", booking.payment_link or "")

    def test_seed_migrates_legacy_minimum_duration_to_two_hours(self) -> None:
        studio = self.db.get(StudioSetting, "standard_small")
        studio.min_duration_hours = 0.5
        self.db.commit()

        seed_studio_settings(self.db)

        self.assertEqual(studio.min_duration_hours, 2.0)

    def test_seed_migrates_previous_public_studio_names_and_slugs(self) -> None:
        standard = self.db.get(StudioSetting, "standard_small")
        premium = self.db.get(StudioSetting, "premium_large")
        standard.name = "Standard Studio"
        standard.slug = "standard-studio"
        standard.brochure = "Standard Studio: previous brochure copy."
        premium.name = "Premium Studio"
        premium.slug = "premium-studio"
        premium.brochure = "Premium Studio: previous brochure copy."
        self.db.commit()

        seed_studio_settings(self.db)

        self.assertEqual((standard.name, standard.slug), ("Cube", "cube"))
        self.assertEqual((premium.name, premium.slug), ("Arena", "arena"))
        self.assertTrue(standard.brochure.startswith("Cube:"))
        self.assertTrue(premium.brochure.startswith("Arena:"))

    def test_inactive_studio_is_hidden_from_public_catalogue(self) -> None:
        admin_update_studio("standard_small", self.payload(is_active=False), self.db)

        self.assertIsNone(get_space_by_id("standard_small", self.db))
        self.assertIsNotNone(get_space_by_id("standard_small", self.db, include_inactive=True))
        self.assertNotIn("standard_small", {space.id for space in list_spaces(self.db)})


if __name__ == "__main__":
    unittest.main()
