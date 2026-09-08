from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from threading import local
from uuid import uuid4
from zoneinfo import ZoneInfo

import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking
from app.services.spaces import StudioSpace, get_space_by_id


_google_calendar_thread_state = local()


@lru_cache(maxsize=4)
def _google_calendar_credentials(key_file: str):
    """Share the short-lived service-account token across worker threads."""
    return service_account.Credentials.from_service_account_file(
        key_file,
        scopes=GoogleCalendarService.scopes,
    )


def _google_calendar_client(key_file: str, timeout_seconds: int):
    """Build one bounded Google client per worker thread and account file.

    ``httplib2.Http`` is not thread-safe, so sharing a single client required a
    process-wide lock. One stalled Google request could therefore freeze every
    public and admin availability request. Thread-local clients retain connection
    reuse without coupling otherwise independent requests. Their credentials are
    shared so a service-account token refresh is not repeated by every FastAPI
    worker thread, while the socket timeout bounds an individual failure.
    """
    clients = getattr(_google_calendar_thread_state, "clients", None)
    if clients is None:
        clients = {}
        _google_calendar_thread_state.clients = clients
    cache_key = (key_file, timeout_seconds)
    client = clients.get(cache_key)
    if client is None:
        credentials = _google_calendar_credentials(key_file)
        transport = AuthorizedHttp(
            credentials,
            http=httplib2.Http(timeout=timeout_seconds),
        )
        client = build(
            "calendar",
            "v3",
            http=transport,
            cache_discovery=False,
        )
        clients[cache_key] = client
    return client


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

    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        self.calendar_id = settings.google_calendar_id.strip()
        self.calendar_ids = {
            "standard_small": settings.google_calendar_standard_small_id.strip(),
            "premium_large": settings.google_calendar_premium_large_id.strip(),
        }
        self.timezone = ZoneInfo(settings.studio_timezone)
        self.mode = settings.calendar_mode.strip().lower()
        if self.mode not in {"stub", "google"}:
            raise RuntimeError("CALENDAR_MODE must be either 'stub' or 'google'.")
        self.service = self._build_service() if self.mode == "google" else None

    def is_available(
        self,
        booking: Booking,
        ignore_event_id: str | None = None,
        events: list[dict] | None = None,
        space: StudioSpace | None = None,
    ) -> bool:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            return False

        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)

        space = space or get_space_by_id(booking.space_id, self.db, include_inactive=True)
        opening = time.fromisoformat(space.opening_time) if space else time(settings.studio_opening_hour)
        closing = time.fromisoformat(space.closing_time) if space else time(settings.studio_closing_hour)
        business_start = datetime.combine(start.date(), opening, tzinfo=self.timezone)
        business_end = datetime.combine(start.date(), closing, tzinfo=self.timezone)
        if start < business_start or end > business_end:
            return False

        if self.mode == "stub":
            return True

        calendar_id = self._calendar_id_for_space(booking.space_id)
        matching_events = [
            event
            for event in (events if events is not None else self._list_events(start, end, calendar_id))
            if (not ignore_event_id or event.get("id") != ignore_event_id)
            and self._event_overlaps_slot(event, start, end)
        ]
        dedicated_calendar = self._uses_dedicated_calendar(booking.space_id)
        if not dedicated_calendar and not self._is_within_business_hours(start, end, matching_events):
            return False

        return not any(
            self._event_blocks_space(event, booking.space_id, dedicated_calendar)
            for event in matching_events
        )

    def events_for_day(
        self,
        space_id: str,
        booking_date: date,
        opening_time: str,
        closing_time: str,
    ) -> list[dict]:
        """Fetch a studio's events once so all slots for a day can be evaluated locally."""
        if self.mode == "stub":
            return []
        start = datetime.combine(
            booking_date,
            time.fromisoformat(opening_time),
            tzinfo=self.timezone,
        )
        end = datetime.combine(
            booking_date,
            time.fromisoformat(closing_time),
            tzinfo=self.timezone,
        )
        return self._list_events(start, end, self._calendar_id_for_space(space_id))

    def create_event(self, booking: Booking) -> str:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            raise ValueError("Booking must have date, start time, and duration before creating a calendar event.")

        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        space_name = space.name if space else "Studio Space"
        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)

        if self.mode == "stub":
            event_id = f"gcal_stub_{uuid4().hex[:12]}"
            print(
                "Google Calendar stub event created:",
                {
                    "event_id": event_id,
                    "space": space_name,
                    "date": booking.booking_date,
                    "start_time": booking.start_time,
                    "duration_hours": booking.duration_hours,
                },
            )
            return event_id

        event = self._event_body(booking, space_name, start, end)
        calendar_id = self._calendar_id_for_space(booking.space_id)

        created_event = (
            self._execute(
                self.service.events().insert(calendarId=calendar_id, body=event)
            )
        )
        return created_event["id"]

    def create_hold_event(self, booking: Booking) -> str:
        """Create an opaque calendar event while the customer completes payment."""
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            raise ValueError("Booking must have a complete schedule before creating a calendar hold.")

        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        space_name = space.name if space else "Studio Space"
        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.razorpay_payment_hold_minutes
        )
        body = self._event_body(booking, space_name, start, end)
        body["summary"] = f"PAYMENT HOLD - {body['summary']}"
        body["description"] = (
            "Booking status: PAYMENT PENDING\n"
            f"Hold expires: {expires_at.astimezone(self.timezone):%d %b %Y, %I:%M %p %Z}\n"
            f"{body['description']}"
        )
        body["transparency"] = "opaque"
        body["colorId"] = "5"
        body["extendedProperties"]["private"]["booking_status"] = "payment_pending"

        if self.mode == "stub":
            event_id = f"gcal_stub_{uuid4().hex[:12]}"
            print(
                "Google Calendar stub hold created:",
                {"event_id": event_id, "space": space_name, "date": booking.booking_date},
            )
            return event_id

        calendar_id = self._calendar_id_for_space(booking.space_id)
        created = self._execute(
            self.service.events().insert(calendarId=calendar_id, body=body)
        )
        return created["id"]

    def update_event(self, booking: Booking, previous_space_id: str | None = None) -> str:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            raise ValueError("Booking must have a complete schedule before updating its calendar event.")

        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        space_name = space.name if space else "Studio Space"
        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)
        if self.mode == "stub":
            event_id = booking.calendar_event_id or f"gcal_stub_{uuid4().hex[:12]}"
            print(
                "Google Calendar stub event updated:",
                {"event_id": event_id, "date": booking.booking_date, "start_time": booking.start_time},
            )
            return event_id

        body = self._event_body(booking, space_name, start, end)
        calendar_id = self._calendar_id_for_space(booking.space_id)
        if booking.calendar_event_id and not booking.calendar_event_id.startswith("gcal_stub_"):
            previous_calendar_id = self._calendar_id_for_space(previous_space_id or booking.space_id)
            if previous_calendar_id != calendar_id:
                self._execute(
                    self.service.events().delete(
                        calendarId=previous_calendar_id,
                        eventId=booking.calendar_event_id,
                    )
                )
                created = self._execute(
                    self.service.events().insert(calendarId=calendar_id, body=body)
                )
                return created["id"]
            updated = self._execute(
                self.service.events().update(
                    calendarId=calendar_id,
                    eventId=booking.calendar_event_id,
                    body=body,
                )
            )
            return updated["id"]

        created = self._execute(
            self.service.events().insert(calendarId=calendar_id, body=body)
        )
        return created["id"]

    def delete_event(self, event_id: str | None, space_id: str | None = None) -> None:
        if not event_id:
            return
        if event_id.startswith("gcal_stub_"):
            print("Legacy Google Calendar stub event skipped:", {"event_id": event_id})
            return
        if self.mode == "stub":
            print("Google Calendar stub event deleted:", {"event_id": event_id})
            return
        calendar_id = self._calendar_id_for_space(space_id)
        self._execute(
            self.service.events().delete(calendarId=calendar_id, eventId=event_id)
        )

    def decline_event(self, booking: Booking) -> str:
        if not booking.booking_date or not booking.start_time or not booking.duration_hours:
            raise ValueError("Booking must have a complete schedule before declining its calendar event.")

        space = get_space_by_id(booking.space_id, self.db, include_inactive=True)
        space_name = space.name if space else "Studio Space"
        start = self._start_datetime(booking)
        end = start + timedelta(hours=booking.duration_hours)
        body = self._event_body(booking, space_name, start, end)
        body["summary"] = f"DECLINED - {body['summary']}"
        body["description"] = f"Booking status: DECLINED / CANCELLED\n{body['description']}"
        body["transparency"] = "transparent"
        body["colorId"] = "11"

        if self.mode == "stub":
            event_id = booking.calendar_event_id or f"gcal_stub_{uuid4().hex[:12]}"
            print("Google Calendar stub event declined:", {"event_id": event_id})
            return event_id

        calendar_id = self._calendar_id_for_space(booking.space_id)
        if booking.calendar_event_id and not booking.calendar_event_id.startswith("gcal_stub_"):
            event = self._execute(
                self.service.events().update(
                    calendarId=calendar_id,
                    eventId=booking.calendar_event_id,
                    body=body,
                )
            )
            return event["id"]

        event = self._execute(
            self.service.events().insert(calendarId=calendar_id, body=body)
        )
        return event["id"]

    def _event_body(
        self,
        booking: Booking,
        space_name: str,
        start: datetime,
        end: datetime,
    ) -> dict:
        customer_name = (booking.customer_name or "Customer").strip()
        contact_number = (booking.phone_number or "No contact number").strip()
        return {
            "summary": f"Booking - {customer_name} - {contact_number}",
            "description": (
                f"Studio: {space_name}\n"
                f"Customer: {customer_name}\n"
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

    def _start_datetime(self, booking: Booking) -> datetime:
        naive_start = datetime.strptime(f"{booking.booking_date} {booking.start_time}", "%Y-%m-%d %H:%M")
        return naive_start.replace(tzinfo=self.timezone)

    def _list_events(self, start: datetime, end: datetime, calendar_id: str) -> list[dict]:
        if self.service is None:
            return []
        response = self._execute(
            self.service.events().list(
                calendarId=calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
        )
        return response.get("items", [])

    @staticmethod
    def _execute(request):
        return request.execute()

    def _event_blocks_space(
        self,
        event: dict,
        requested_space_id: str | None,
        dedicated_calendar: bool = False,
    ) -> bool:
        if event.get("status") == "cancelled":
            return False
        if event.get("transparency") == "transparent":
            return False

        if dedicated_calendar:
            return True

        if self._event_blocks_all_spaces(event):
            return True

        private_properties = event.get("extendedProperties", {}).get("private", {})
        event_space_id = private_properties.get("space_id")
        if event_space_id:
            return event_space_id == requested_space_id

        space = get_space_by_id(requested_space_id, self.db, include_inactive=True)
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

    def _event_overlaps_slot(self, event: dict, start: datetime, end: datetime) -> bool:
        event_start = self._parse_event_datetime(event.get("start", {}), is_end=False)
        event_end = self._parse_event_datetime(event.get("end", {}), is_end=True)
        return start < event_end and event_start < end

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
        if not self.calendar_id and not any(self.calendar_ids.values()):
            raise RuntimeError(
                "Google Calendar IDs are missing. Configure the per-studio calendar IDs in your .env file."
            )

        key_path = Path(settings.google_service_account_file)
        if not key_path.exists():
            raise RuntimeError(
                f"Google service account file not found at {key_path}. "
                "Set GOOGLE_SERVICE_ACCOUNT_FILE in your .env file."
            )

        return _google_calendar_client(
            str(key_path.resolve()),
            max(1, settings.google_calendar_timeout_seconds),
        )

    def _calendar_id_for_space(self, space_id: str | None) -> str:
        calendar_id = self.calendar_ids.get(space_id or "") or self.calendar_id
        if not calendar_id:
            raise RuntimeError(f"No Google Calendar ID is configured for studio space '{space_id or 'unknown'}'.")
        return calendar_id

    def _uses_dedicated_calendar(self, space_id: str | None) -> bool:
        return bool(self.calendar_ids.get(space_id or ""))
