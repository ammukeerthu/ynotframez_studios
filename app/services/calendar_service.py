from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.core.config import settings
from app.models.booking import Booking
from app.services.spaces import get_space_by_id


class GoogleCalendarService:
    """Google Calendar availability and event sync using a service account."""

    scopes = ["https://www.googleapis.com/auth/calendar"]
    non_business_keywords = (
        "closed",
        "closure",
        "holiday",
        "ooo",
        "out of office",
        "unavailable",
        "non-business",
        "non business",
    )
    business_hours_keywords = (
        "business hours",
        "business hour",
        "open hours",
        "working hours",
        "studio open",
        "available for booking",
    )

    def __init__(self) -> None:
        self.calendar_id = settings.google_calendar_id
        self.timezone = ZoneInfo(settings.studio_timezone)
        self.service = self._build_service()

    def is_available(self, booking: Booking) -> bool:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            return False

        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)

        events = self._list_events(start, end)
        if not self._is_within_business_hours(start, end, events):
            return False

        return not any(self._event_blocks_space(event, booking.space_id) for event in events)

    def create_event(self, booking: Booking) -> str:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            raise ValueError("Booking must have date, start time, and duration before creating a calendar event.")

        space = get_space_by_id(booking.space_id)
        space_name = space.name if space else "Studio Space"
        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)
        event = {
            "summary": f"{space_name} booking - {booking.customer_name}",
            "description": (
                f"Customer: {booking.customer_name}\n"
                f"Phone: {booking.phone_number}\n"
                f"Email: {booking.customer_email}\n"
                f"Purpose: {booking.purpose}\n"
                f"Payment mode: {booking.payment_mode}"
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": settings.studio_timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": settings.studio_timezone},
            "extendedProperties": {
                "private": {
                    "booking_id": str(booking.id),
                    "space_id": booking.space_id or "",
                }
            },
        }

        created_event = (
            self.service.events()
            .insert(calendarId=self.calendar_id, body=event)
            .execute()
        )
        return created_event["id"]

    def _start_datetime(self, booking: Booking) -> datetime:
        naive_start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
        return naive_start.replace(tzinfo=self.timezone)

    def _list_events(self, start: datetime, end: datetime) -> list[dict]:
        response = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return response.get("items", [])

    def _event_blocks_space(self, event: dict, requested_space_id: str | None) -> bool:
        if event.get("status") == "cancelled":
            return False

        if self._event_blocks_all_spaces(event):
            return True

        private_properties = event.get("extendedProperties", {}).get("private", {})
        event_space_id = private_properties.get("space_id")
        if event_space_id:
            return event_space_id == requested_space_id

        space = get_space_by_id(requested_space_id)
        event_text = f"{event.get('summary', '')}\n{event.get('description', '')}".lower()
        if space and (space.id.lower() in event_text or space.name.lower() in event_text):
            return True

        return False

    def _event_blocks_all_spaces(self, event: dict) -> bool:
        if event.get("eventType") == "outOfOffice":
            return True

        event_text = f"{event.get('summary', '')}\n{event.get('description', '')}".lower()
        return any(keyword in event_text for keyword in self.non_business_keywords)

    def _is_within_business_hours(self, start: datetime, end: datetime, events: list[dict]) -> bool:
        business_hour_events = [event for event in events if self._event_is_business_hours(event)]
        return any(self._event_contains_slot(event, start, end) for event in business_hour_events)

    def _event_is_business_hours(self, event: dict) -> bool:
        if event.get("status") == "cancelled":
            return False

        event_text = f"{event.get('summary', '')}\n{event.get('description', '')}".lower()
        return any(keyword in event_text for keyword in self.business_hours_keywords)

    def _event_contains_slot(self, event: dict, start: datetime, end: datetime) -> bool:
        event_start = self._parse_event_datetime(event.get("start", {}), is_end=False)
        event_end = self._parse_event_datetime(event.get("end", {}), is_end=True)
        return event_start <= start and end <= event_end

    def _parse_event_datetime(self, value: dict, is_end: bool) -> datetime:
        if "dateTime" in value:
            raw_value = value["dateTime"].replace("Z", "+00:00")
            parsed = datetime.fromisoformat(raw_value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=self.timezone)
            return parsed.astimezone(self.timezone)

        raw_date = date.fromisoformat(value["date"])
        if is_end:
            raw_date = raw_date - timedelta(days=1)
        event_time = time.max if is_end else time.min
        return datetime.combine(raw_date, event_time, tzinfo=self.timezone)

    def _build_service(self):
        if not self.calendar_id:
            raise RuntimeError("GOOGLE_CALENDAR_ID is missing. Add it to your .env file.")

        key_path = Path(settings.google_service_account_file)
        if not key_path.exists():
            raise RuntimeError(
                f"Google service account file not found at {key_path}. "
                "Set GOOGLE_SERVICE_ACCOUNT_FILE in your .env file."
            )

        credentials = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=self.scopes,
        )
        return build("calendar", "v3", credentials=credentials)
