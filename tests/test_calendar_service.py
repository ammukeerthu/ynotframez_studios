import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.models.booking import Booking
from app.core.config import settings
from app.services.calendar_service import GoogleCalendarService

settings.calendar_mode = "stub"


class GoogleCalendarServiceTest(unittest.TestCase):
    def service(self) -> GoogleCalendarService:
        service = GoogleCalendarService()
        service.calendar_id = "legacy-calendar"
        service.calendar_ids = {
            "standard_small": "standard-calendar",
            "premium_large": "premium-calendar",
        }
        return service

    def test_each_studio_uses_its_dedicated_calendar_with_legacy_fallback(self) -> None:
        service = self.service()

        self.assertEqual(service._calendar_id_for_space("standard_small"), "standard-calendar")
        self.assertEqual(service._calendar_id_for_space("premium_large"), "premium-calendar")
        self.assertEqual(service._calendar_id_for_space("future_space"), "legacy-calendar")
        self.assertTrue(service._uses_dedicated_calendar("standard_small"))
        self.assertFalse(service._uses_dedicated_calendar("future_space"))

    def test_normal_busy_events_block_a_dedicated_studio_calendar(self) -> None:
        service = self.service()

        self.assertTrue(service._event_blocks_space({"summary": "Owner hold"}, "standard_small", True))
        self.assertFalse(
            service._event_blocks_space(
                {"summary": "FYI", "transparency": "transparent"},
                "standard_small",
                True,
            )
        )

    def test_event_title_contains_customer_name_and_contact_number(self) -> None:
        service = self.service()
        booking = Booking(
            id=44,
            phone_number="+919876543210",
            space_id="standard_small",
            customer_name="Keerthana",
            customer_email="keerthana@example.com",
            purpose="Fashion Shoot",
        )

        body = service._event_body(
            booking,
            "Standard Studio",
            datetime(2026, 9, 20, 14, 30, tzinfo=service.timezone),
            datetime(2026, 9, 20, 15, 30, tzinfo=service.timezone),
        )

        self.assertEqual(body["summary"], "Booking - Keerthana - +919876543210")
        self.assertIn("Studio: Standard Studio", body["description"])
        self.assertFalse(
            service._event_blocks_space(
                {"summary": "Removed", "status": "cancelled"},
                "standard_small",
                True,
            )
        )

    def test_moving_a_booking_moves_its_google_event_between_calendars(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.delete.return_value.execute.return_value = {}
        events.insert.return_value.execute.return_value = {"id": "new-premium-event"}
        booking = Booking(
            id=42,
            phone_number="+919999999999",
            space_id="premium_large",
            booking_date="2026-09-20",
            start_time="14:30",
            duration_hours=1.5,
            customer_name="Calendar Customer",
            customer_email="calendar@example.com",
            purpose="Fashion Shoot",
            calendar_event_id="old-standard-event",
        )

        event_id = service.update_event(booking, previous_space_id="standard_small")

        events.delete.assert_called_once_with(
            calendarId="standard-calendar",
            eventId="old-standard-event",
        )
        events.insert.assert_called_once()
        self.assertEqual(events.insert.call_args.kwargs["calendarId"], "premium-calendar")
        self.assertEqual(event_id, "new-premium-event")

    def test_updating_a_legacy_stub_booking_creates_its_first_live_event(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.insert.return_value.execute.return_value = {"id": "first-live-event"}
        booking = Booking(
            id=43,
            phone_number="+919999999999",
            space_id="standard_small",
            booking_date="2026-09-20",
            start_time="14:30",
            duration_hours=1,
            customer_name="Legacy Customer",
            customer_email="legacy@example.com",
            purpose="Fashion Shoot",
            calendar_event_id="gcal_stub_123456789abc",
        )

        event_id = service.update_event(booking)

        events.update.assert_not_called()
        events.insert.assert_called_once()
        self.assertEqual(event_id, "first-live-event")

    def test_deleting_a_legacy_stub_id_does_not_call_google(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()

        service.delete_event("gcal_stub_123456789abc", "standard_small")

        service.service.events.assert_not_called()

    def test_declined_event_remains_visible_but_does_not_block_time(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.update.return_value.execute.return_value = {"id": "live-event"}
        booking = Booking(
            id=45,
            phone_number="+919876543210",
            space_id="standard_small",
            booking_date="2026-09-20",
            start_time="14:30",
            duration_hours=1,
            customer_name="Cancelled Customer",
            customer_email="cancelled@example.com",
            purpose="Fashion Shoot",
            calendar_event_id="live-event",
        )

        event_id = service.decline_event(booking)

        body = events.update.call_args.kwargs["body"]
        self.assertEqual(body["summary"], "DECLINED - Booking - Cancelled Customer - +919876543210")
        self.assertEqual(body["transparency"], "transparent")
        self.assertEqual(body["colorId"], "11")
        self.assertFalse(service._event_blocks_space(body, "standard_small", True))
        self.assertEqual(event_id, "live-event")


if __name__ == "__main__":
    unittest.main()
