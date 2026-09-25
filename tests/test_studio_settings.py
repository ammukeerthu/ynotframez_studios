import json
import unittest
from datetime import date, time, timedelta

from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import admin_studios, admin_update_studio
from app.core.database import Base
from app.core.config import settings
from app.schemas.admin import AdminStudioUpdate
from app.schemas.booking import AvailabilityRequest, WebBookingCreate
from app.services.booking_service import BookingApplicationService
from app.services.spaces import (
    get_space_by_id,
    get_space_by_slug,
    invalidate_public_space_cache,
    list_public_spaces_cached,
    list_spaces,
    overwrite_studio_settings_with_defaults,
    seed_studio_settings,
)
from app.models.studio import StudioPurposeOption, StudioSetting

settings.email_mode = "console"
settings.calendar_mode = "stub"
settings.razorpay_mode = "stub"


class StudioSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        invalidate_public_space_cache()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        seed_studio_settings(self.db)

    def tearDown(self) -> None:
        invalidate_public_space_cache()
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
        self.assertIsNotNone(booking.checkout)
        self.assertEqual(booking.checkout.amount, 320000)

    def test_seed_enforces_the_one_hour_global_floor(self) -> None:
        studio = self.db.get(StudioSetting, "standard_small")
        studio.min_duration_hours = 0.5
        self.db.commit()

        seed_studio_settings(self.db)

        self.assertEqual(studio.min_duration_hours, 1.0)

    def test_seed_migrates_the_previous_default_closing_time(self) -> None:
        studio = self.db.get(StudioSetting, "standard_small")
        studio.opening_time = "09:00"
        studio.closing_time = "20:00"
        self.db.commit()

        seed_studio_settings(self.db)

        self.assertEqual(studio.closing_time, "21:00")

    def test_seed_preserves_owner_managed_custom_hours(self) -> None:
        studio = self.db.get(StudioSetting, "standard_small")
        studio.opening_time = "10:00"
        studio.closing_time = "18:00"
        self.db.commit()

        seed_studio_settings(self.db)

        self.assertEqual((studio.opening_time, studio.closing_time), ("10:00", "18:00"))

    def test_seed_migrates_previous_arena_capacity_and_cyclorama_labels(self) -> None:
        arena = self.db.get(StudioSetting, "premium_large")
        arena.capacity = 10
        arena.equipment_json = json.dumps(
            ["Approx. 150 sq. ft. Cyclorama", "Custom production light"]
        )
        arena.amenities_json = json.dumps(
            ["Approx. 150 sq. ft. Cyclorama", "Custom client lounge"]
        )
        self.db.commit()

        seed_studio_settings(self.db)
        migrated = get_space_by_id("premium_large", self.db, include_inactive=True)

        self.assertEqual(migrated.capacity, 8)
        self.assertEqual(migrated.equipment, ("Cyclorama", "Custom production light"))
        self.assertEqual(migrated.amenities, ("Cyclorama", "Custom client lounge"))

    def test_seed_preserves_custom_arena_values(self) -> None:
        arena = self.db.get(StudioSetting, "premium_large")
        arena.capacity = 12
        arena.equipment_json = json.dumps(["Custom cyc wall description"])
        arena.amenities_json = json.dumps(["Custom production amenity"])
        self.db.commit()

        seed_studio_settings(self.db)
        preserved = get_space_by_id("premium_large", self.db, include_inactive=True)

        self.assertEqual(preserved.capacity, 12)
        self.assertEqual(preserved.equipment, ("Custom cyc wall description",))
        self.assertEqual(preserved.amenities, ("Custom production amenity",))

    def test_seed_renames_and_repositions_the_previous_arena_family_purpose_once(self) -> None:
        self.db.execute(
            text(
                "DELETE FROM app_migrations "
                "WHERE migration_key = 'rename_and_position_arena_family_portraits'"
            )
        )
        family_purpose = self.db.scalar(
            select(StudioPurposeOption).where(
                StudioPurposeOption.space_id == "premium_large",
                StudioPurposeOption.label == "Family Portraits",
            )
        )
        family_purpose.label = "Family Shoots"
        family_purpose.sort_order = 98
        self.db.add(
            StudioPurposeOption(
                space_id="premium_large",
                label="Custom Arena Purpose",
                sort_order=99,
            )
        )
        self.db.commit()

        seed_studio_settings(self.db)
        seed_studio_settings(self.db)
        arena = get_space_by_id("premium_large", self.db, include_inactive=True)

        self.assertIn("Custom Arena Purpose", arena.booking_purposes)
        self.assertEqual(arena.booking_purposes.count("Family Portraits"), 1)
        self.assertNotIn("Family Shoots", arena.booking_purposes)
        self.assertEqual(arena.booking_purposes[0:2], ("Fashion Shoot", "Family Portraits"))
        self.assertEqual(arena.booking_purposes[-1], "Custom Arena Purpose")

    def test_seed_adds_fine_arts_to_both_studios_without_replacing_custom_purposes(self) -> None:
        self.db.execute(
            text(
                "DELETE FROM app_migrations "
                "WHERE migration_key = 'add_and_position_fine_arts_purposes'"
            )
        )
        self.db.execute(
            delete(StudioPurposeOption).where(StudioPurposeOption.label == "Fine Arts")
        )
        self.db.add(
            StudioPurposeOption(
                space_id="standard_small",
                label="Custom Cube Purpose",
                sort_order=98,
            )
        )
        self.db.add(
            StudioPurposeOption(
                space_id="premium_large",
                label="Custom Arena Purpose",
                sort_order=98,
            )
        )
        self.db.commit()

        seed_studio_settings(self.db)
        seed_studio_settings(self.db)
        cube = get_space_by_id("standard_small", self.db, include_inactive=True)
        arena = get_space_by_id("premium_large", self.db, include_inactive=True)

        for studio, custom_purpose in (
            (cube, "Custom Cube Purpose"),
            (arena, "Custom Arena Purpose"),
        ):
            self.assertEqual(studio.booking_purposes.count("Fine Arts"), 1)
            self.assertIn(custom_purpose, studio.booking_purposes)
            creative_index = studio.booking_purposes.index("Creative / Conceptual Shoot")
            self.assertEqual(studio.booking_purposes[creative_index + 1], "Fine Arts")

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

    def test_explicit_default_sync_overwrites_saved_profiles_and_purposes(self) -> None:
        admin_update_studio("standard_small", self.payload(), self.db)

        overwrite_studio_settings_with_defaults(self.db)

        standard = get_space_by_id("standard_small", self.db)
        premium = get_space_by_id("premium_large", self.db)
        self.assertEqual((standard.name, standard.hourly_rate, standard.capacity), ("Cube", 1000, 5))
        self.assertEqual(standard.booking_purposes[0], "Portrait Shoot")
        self.assertIn("Fine Arts", standard.booking_purposes)
        self.assertEqual((premium.name, premium.hourly_rate, premium.capacity), ("Arena", 1500, 8))
        self.assertEqual(premium.booking_purposes[0:2], ("Fashion Shoot", "Family Portraits"))
        self.assertIn("Fine Arts", premium.booking_purposes)
        self.assertEqual(premium.booking_purposes[-1], "Larger Productions")

    def test_inactive_studio_is_hidden_from_public_catalogue(self) -> None:
        admin_update_studio("standard_small", self.payload(is_active=False), self.db)

        self.assertIsNone(get_space_by_id("standard_small", self.db))
        self.assertIsNotNone(get_space_by_id("standard_small", self.db, include_inactive=True))
        self.assertNotIn("standard_small", {space.id for space in list_spaces(self.db)})

    def test_public_studio_list_uses_two_database_queries(self) -> None:
        statements = []

        def track_statement(*args) -> None:
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", track_statement)
        try:
            spaces = list_spaces(self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", track_statement)

        self.assertEqual([space.name for space in spaces], ["Cube", "Arena"])
        self.assertEqual(len(statements), 2)

    def test_single_studio_lookup_does_not_load_the_full_catalogue(self) -> None:
        statements = []

        def track_statement(*args) -> None:
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", track_statement)
        try:
            space = get_space_by_slug("cube", self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", track_statement)

        self.assertEqual(space.name, "Cube")
        self.assertEqual(len(statements), 2)

    def test_admin_save_invalidates_the_public_studio_cache(self) -> None:
        cached = list_public_spaces_cached(self.db)
        self.assertEqual(cached[0].name, "Cube")

        admin_update_studio("standard_small", self.payload(), self.db)
        refreshed = list_public_spaces_cached(self.db)

        self.assertEqual(refreshed[0].name, "Standard Creator Space")


if __name__ == "__main__":
    unittest.main()
