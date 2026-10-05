import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError

from app.models.booking import Booking
from app.models.availability import AvailabilityBlock
from app.core.config import settings
from app.services.calendar_service import (
    GoogleCalendarService,
    _google_calendar_client,
    _google_calendar_credentials,
    _google_calendar_thread_state,
)

settings.calendar_mode = "stub"


class GoogleCalendarServiceTest(unittest.TestCase):
    def tearDown(self) -> None:
        if hasattr(_google_calendar_thread_state, "clients"):
            del _google_calendar_thread_state.clients
        _google_calendar_credentials.cache_clear()

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

    @patch("app.services.calendar_service.build")
    @patch("app.services.calendar_service.AuthorizedHttp")
    @patch("app.services.calendar_service.httplib2.Http")
    @patch("app.services.calendar_service.service_account.Credentials.from_service_account_file")
    def test_google_client_reuses_a_bounded_thread_local_transport(
        self,
        credentials_from_file: MagicMock,
        http: MagicMock,
        authorized_http: MagicMock,
        build: MagicMock,
    ) -> None:
        expected_client = build.return_value

        first = _google_calendar_client("calendar-key.json", 8)
        second = _google_calendar_client("calendar-key.json", 8)

        self.assertIs(first, expected_client)
        self.assertIs(second, expected_client)
        credentials_from_file.assert_called_once_with(
            "calendar-key.json",
            scopes=GoogleCalendarService.scopes,
        )
        http.assert_called_once_with(timeout=8)
        authorized_http.assert_called_once_with(
            credentials_from_file.return_value,
            http=http.return_value,
        )
        build.assert_called_once_with(
            "calendar",
            "v3",
            http=authorized_http.return_value,
            cache_discovery=False,
        )

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
            "Cube",
            datetime(2026, 9, 20, 14, 30, tzinfo=service.timezone),
            datetime(2026, 9, 20, 15, 30, tzinfo=service.timezone),
        )

        self.assertEqual(body["summary"], "Booking - Keerthana - +919876543210")
        self.assertIn("Studio: Cube", body["description"])
        self.assertFalse(
            service._event_blocks_space(
                {"summary": "Removed", "status": "cancelled"},
                "standard_small",
                True,
            )
        )

    def test_payment_hold_is_created_as_an_opaque_busy_event(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.insert.return_value.execute.return_value = {"id": "hold-event"}
        booking = Booking(
            id=46,
            phone_number="+919876543210",
            space_id="standard_small",
            booking_date="2026-09-20",
            start_time="14:30",
            duration_hours=2,
            customer_name="Pending Customer",
            customer_email="pending@example.com",
            purpose="Fashion Shoot",
        )

        event_id = service.create_hold_event(booking)

        body = events.insert.call_args.kwargs["body"]
        self.assertEqual(event_id, "hold-event")
        self.assertTrue(body["summary"].startswith("PAYMENT HOLD - Booking - Pending Customer"))
        self.assertEqual(body["transparency"], "opaque")
        self.assertEqual(body["extendedProperties"]["private"]["booking_status"], "payment_pending")
        self.assertIn("Hold expires:", body["description"])

    def test_availability_block_creates_an_opaque_reasoned_event(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.insert.return_value.execute.return_value = {"id": "block-event"}
        block = AvailabilityBlock(
            id=12,
            space_id="standard_small",
            booking_date="2026-09-20",
            start_time="14:30",
            duration_hours=1.5,
            reason="Collaboration",
            collaboration_name="North Star Collective",
            collaboration_contact="team@example.com",
            collaboration_details="Editorial test shoot",
        )

        event_id = service.create_availability_block_event(block)

        body = events.insert.call_args.kwargs["body"]
        self.assertEqual(event_id, "block-event")
        self.assertEqual(events.insert.call_args.kwargs["calendarId"], "standard-calendar")
        self.assertEqual(body["summary"], "BLOCKED - Collaboration - North Star Collective")
        self.assertEqual(body["transparency"], "opaque")
        self.assertEqual(body["colorId"], "8")
        self.assertEqual(
            body["extendedProperties"]["private"]["availability_block_id"],
            "12",
        )
        self.assertEqual(body["extendedProperties"]["private"]["space_id"], "standard_small")
        self.assertIn("Studio: Cube", body["description"])
        self.assertIn("Reason: Collaboration", body["description"])
        self.assertIn("Used by: North Star Collective", body["description"])
        self.assertIn("Contact: team@example.com", body["description"])
        self.assertIn("Details: Editorial test shoot", body["description"])

    def test_availability_block_update_reuses_its_linked_event(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.update.return_value.execute.return_value = {"id": "block-event"}
        block = AvailabilityBlock(
            id=12,
            space_id="premium_large",
            booking_date="2026-09-20",
            start_time="15:00",
            duration_hours=1,
            reason="Maintenance",
            calendar_event_id="block-event",
        )

        event_id = service.update_availability_block_event(block)

        self.assertEqual(event_id, "block-event")
        events.update.assert_called_once()
        self.assertEqual(events.update.call_args.kwargs["calendarId"], "premium-calendar")
        self.assertEqual(events.update.call_args.kwargs["eventId"], "block-event")
        self.assertEqual(events.update.call_args.kwargs["body"]["summary"], "BLOCKED - Maintenance")

    def test_missing_availability_block_event_is_recreated_or_treated_as_deleted(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        missing = HttpError(MagicMock(status=404, reason="Not found"), b"{}")
        events.update.return_value.execute.side_effect = missing
        events.insert.return_value.execute.return_value = {"id": "replacement-block-event"}
        block = AvailabilityBlock(
            id=12,
            space_id="standard_small",
            booking_date="2026-09-20",
            start_time="15:00",
            duration_hours=1,
            reason="Maintenance",
            calendar_event_id="missing-block-event",
        )

        event_id = service.update_availability_block_event(block)

        self.assertEqual(event_id, "replacement-block-event")
        events.insert.assert_called_once()

        events.delete.return_value.execute.side_effect = missing
        service.delete_availability_block_event(block)

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

    def test_failed_destination_calendar_insert_keeps_the_original_event(self) -> None:
        service = self.service()
        service.mode = "google"
        service.service = MagicMock()
        events = service.service.events.return_value
        events.insert.return_value.execute.side_effect = RuntimeError("destination unavailable")
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

        with self.assertRaisesRegex(RuntimeError, "destination unavailable"):
            service.update_event(booking, previous_space_id="standard_small")

        events.delete.assert_not_called()

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
