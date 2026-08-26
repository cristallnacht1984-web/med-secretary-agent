"""Calendar Service with OAuth2 authentication for Google Calendar API."""
import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Settings, get_settings
from app.logging_setup import get_logger, new_request_id

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readwrite"]


class CalendarAuthError(RuntimeError):
    """Ошибка аутентификации Google Calendar."""

    pass


class CalendarAPIError(RuntimeError):
    """Ошибка вызова Google Calendar API."""

    pass


class CalendarService:
    """Service for Google Calendar operations with OAuth2 authentication."""

    def __init__(self, settings: Settings | None = None):
        """Initialize CalendarService with optional settings.

        Args:
            settings: Application settings. If None, uses get_settings().
        """
        self._settings = settings if settings is not None else get_settings()
        self._logger = get_logger("calendar")
        self._credentials: Credentials | None = None
        self._service: Any | None = None

    async def authenticate(self) -> None:
        """Authenticate with Google Calendar API.

        Loads credentials from file, refreshes if expired, or raises CalendarAuthError.
        """
        request_id = new_request_id()
        async with asyncio.Lock():
            try:
                self._credentials = await asyncio.to_thread(self._load_credentials_from_file)
                self._logger.info(
                    "Credentials loaded from file",
                    extra={"request_id": request_id},
                )
            except CalendarAuthError:
                self._logger.info(
                    "No credentials file found, starting OAuth flow",
                    extra={"request_id": request_id},
                )
                raise

            if self._credentials.expired and self._credentials.refresh_token:
                try:
                    self._credentials = await asyncio.to_thread(
                        self._refresh_token, self._credentials
                    )
                    self._logger.info(
                        "Token refreshed successfully",
                        extra={"request_id": request_id},
                    )
                except CalendarAuthError as e:
                    self._logger.error(
                        f"Token refresh failed: {e}",
                        extra={"request_id": request_id},
                    )
                    raise
            elif not self._credentials.valid:
                self._logger.warning(
                    "Credentials invalid and no refresh token available",
                    extra={"request_id": request_id},
                )
                raise CalendarAuthError("Credentials invalid and no refresh token available")

            await asyncio.to_thread(self._save_token, self._credentials)
            self._logger.info(
                "Authentication successful",
                extra={"request_id": request_id},
            )

    def _load_credentials_from_file(self) -> Credentials:
        """Load credentials from token file.

        Returns:
            Loaded Credentials object.

        Raises:
            CalendarAuthError: If file doesn't exist or JSON is invalid.
        """
        token_file = self._settings.GOOGLE_TOKEN_FILE

        if not token_file.exists():
            raise CalendarAuthError(f"Token file not found: {token_file}")

        try:
            content = token_file.read_text(encoding="utf-8")
            token_data = json.loads(content)
        except OSError as e:
            raise CalendarAuthError(f"Failed to read token file: {e}") from e
        except json.JSONDecodeError as e:
            raise CalendarAuthError(f"Invalid JSON in token file: {e}") from e

        try:
            credentials = Credentials.from_authorized_user_info(token_data, SCOPES)
        except (ValueError, TypeError) as e:
            raise CalendarAuthError(f"Failed to parse credentials: {e}") from e

        return credentials

    def _refresh_token(self, credentials: Credentials) -> Credentials:
        """Refresh expired credentials.

        Args:
            credentials: Expired credentials to refresh.

        Returns:
            Refreshed Credentials object.

        Raises:
            CalendarAuthError: If refresh fails.
        """
        try:
            credentials.refresh(Request())
        except Exception as e:
            raise CalendarAuthError(f"Token refresh failed: {e}") from e

        if not credentials.valid:
            raise CalendarAuthError("Token refresh did not produce valid credentials")

        return credentials

    def _save_token(self, credentials: Credentials) -> None:
        """Save credentials to token file.

        Args:
            credentials: Credentials to save.
        """
        token_file = self._settings.GOOGLE_TOKEN_FILE

        try:
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_data = {
                "token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_uri": credentials.token_uri,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scopes": credentials.scopes,
            }
            if credentials.expiry:
                token_data["expiry"] = credentials.expiry.isoformat()

            token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        except OSError as e:
            self._logger.warning(f"Failed to save token file: {e}")

    async def _get_service(self):
        """Get authenticated Google Calendar API service.

        Returns:
            Authenticated Calendar API service.

        Raises:
            CalendarAuthError: If not authenticated.
        """
        if self._credentials is None or not self._credentials.valid:
            raise CalendarAuthError("Not authenticated. Call authenticate() first.")

        if self._service is None:
            self._service = await asyncio.to_thread(
                lambda: build("calendar", "v3", credentials=self._credentials)
            )
            self._logger.info("Calendar service initialized")

        return self._service

    async def _retry_with_backoff(
        self,
        func: Callable,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Any:
        """Execute function with exponential backoff retry.

        Args:
            func: Sync function to execute (will be wrapped in asyncio.to_thread).
            max_retries: Maximum number of retry attempts.
            base_delay: Base delay in seconds (delay = base_delay * 2**attempt).

        Returns:
            Result of successful function call.

        Raises:
            CalendarAPIError: If all retries fail or non-retryable error occurs.
        """
        for attempt in range(max_retries):
            try:
                # Wrap sync function in asyncio.to_thread
                return await asyncio.to_thread(func)
            except HttpError as e:
                status_code = e.status_code
                # Retry on 5xx and 429, not on other 4xx
                if status_code in (500, 502, 503, 504, 429):
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        self._logger.warning(
                            "HTTP %d error, retrying in %.1fs (attempt %d/%d)",
                            status_code,
                            delay,
                            attempt + 1,
                            max_retries,
                        )
                        await asyncio.sleep(delay)
                    else:
                        self._logger.error(
                            "HTTP %d error after %d attempts",
                            status_code,
                            max_retries,
                        )
                        raise CalendarAPIError(f"HTTP {status_code}: {e.reason}") from e
                else:
                    # Non-retryable 4xx error
                    if status_code == 404:
                        raise CalendarAPIError("Event not found") from e
                    raise CalendarAPIError(f"HTTP {status_code}: {e.reason}") from e
            except TimeoutError as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    self._logger.warning(
                        "Timeout error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                else:
                    self._logger.error("Timeout error after %d attempts", max_retries)
                    raise CalendarAPIError("Request timeout") from e
            except Exception as e:
                # Connection errors and other exceptions - retry
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    self._logger.warning(
                        "%s error, retrying in %.1fs (attempt %d/%d)",
                        type(e).__name__,
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                else:
                    self._logger.error(
                        "%s error after %d attempts",
                        type(e).__name__,
                        max_retries,
                    )
                    raise CalendarAPIError(f"Request failed: {e}") from e

        # Should not reach here, but just in case
        raise CalendarAPIError(f"Request failed after {max_retries} attempts")

    async def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: str | None = None,
        location: str | None = None,
        timezone: str | None = None,
    ) -> str:
        """Create a new event in Google Calendar.

        Args:
            summary: Event title/summary.
            start_time: Event start time (UTC datetime).
            end_time: Event end time (UTC datetime).
            description: Optional event description.
            location: Optional event location.
            timezone: Optional timezone for display (defaults to settings.TIMEZONE).

        Returns:
            Event ID string.

        Raises:
            CalendarAPIError: If API call fails.
            CalendarAuthError: If not authenticated.
        """
        service = await self._get_service()
        tz = timezone if timezone is not None else str(self._settings.TIMEZONE)

        # Convert datetime to RFC3339 format (ISO 8601 with timezone)
        # Ensure datetimes are UTC and aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        event_body = {
            "summary": summary,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": tz,
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": tz,
            },
        }

        if description is not None:
            event_body["description"] = description
        if location is not None:
            event_body["location"] = location

        request_id = new_request_id()
        self._logger.info(f"Creating event: {summary}", extra={"request_id": request_id})

        def _insert():
            return service.events().insert(
                calendarId=self._settings.GOOGLE_CALENDAR_ID,
                body=event_body,
            ).execute()

        try:
            result = await self._retry_with_backoff(_insert)
            event_id = result.get("id")
            self._logger.info(
                f"Event created successfully: {event_id}",
                extra={"request_id": request_id},
            )
            return event_id
        except CalendarAPIError as e:
            self._logger.error(
                f"Failed to create event: {e}",
                extra={"request_id": request_id},
            )
            raise

    async def get_event(self, event_id: str) -> dict:
        """Get an event by ID from Google Calendar.

        Args:
            event_id: The event ID to retrieve.

        Returns:
            Dict with keys: id, summary, start, end, description, location.

        Raises:
            CalendarAPIError: If event not found (404) or API call fails.
            CalendarAuthError: If not authenticated.
        """
        service = await self._get_service()
        request_id = new_request_id()
        self._logger.info(f"Getting event: {event_id}", extra={"request_id": request_id})

        def _get():
            return service.events().get(
                calendarId=self._settings.GOOGLE_CALENDAR_ID,
                eventId=event_id,
            ).execute()

        try:
            result = await self._retry_with_backoff(_get)
            event_data = {
                "id": result.get("id"),
                "summary": result.get("summary"),
                "start": result.get("start", {}).get("dateTime"),
                "end": result.get("end", {}).get("dateTime"),
                "description": result.get("description"),
                "location": result.get("location"),
            }
            self._logger.info(
                f"Event retrieved successfully: {event_id}",
                extra={"request_id": request_id},
            )
            return event_data
        except CalendarAPIError as e:
            if "Event not found" in str(e):
                self._logger.error(
                    f"Event not found: {event_id}",
                    extra={"request_id": request_id},
                )
            else:
                self._logger.error(
                    f"Failed to get event {event_id}: {e}",
                    extra={"request_id": request_id},
                )
            raise

    async def update_event(
        self,
        event_id: str,
        summary: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> str:
        """Update an existing event in Google Calendar (PATCH/partial update).

        Args:
            event_id: The event ID to update.
            summary: New event title (optional).
            start_time: New start time (optional, UTC datetime).
            end_time: New end time (optional, UTC datetime).
            description: New description (optional).
            location: New location (optional).

        Returns:
            Event ID string.

        Raises:
            CalendarAPIError: If event not found (404) or API call fails.
            CalendarAuthError: If not authenticated.
        """
        service = await self._get_service()
        request_id = new_request_id()
        self._logger.info(f"Updating event: {event_id}", extra={"request_id": request_id})

        # Build patch body with only provided fields
        patch_body = {}

        if summary is not None:
            patch_body["summary"] = summary

        if start_time is not None or end_time is not None:
            tz = str(self._settings.TIMEZONE)
            if start_time is not None:
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=UTC)
                patch_body["start"] = {
                    "dateTime": start_time.isoformat(),
                    "timeZone": tz,
                }
            if end_time is not None:
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=UTC)
                patch_body["end"] = {
                    "dateTime": end_time.isoformat(),
                    "timeZone": tz,
                }

        if description is not None:
            patch_body["description"] = description

        if location is not None:
            patch_body["location"] = location

        def _patch():
            return service.events().patch(
                calendarId=self._settings.GOOGLE_CALENDAR_ID,
                eventId=event_id,
                body=patch_body,
            ).execute()

        try:
            result = await self._retry_with_backoff(_patch)
            updated_id = result.get("id")
            self._logger.info(
                f"Event updated successfully: {updated_id}",
                extra={"request_id": request_id},
            )
            return updated_id
        except CalendarAPIError as e:
            if "Event not found" in str(e):
                self._logger.error(
                    f"Event not found: {event_id}",
                    extra={"request_id": request_id},
                )
            else:
                self._logger.error(
                    f"Failed to update event {event_id}: {e}",
                    extra={"request_id": request_id},
                )
            raise

    async def delete_event(self, event_id: str) -> None:
        """Delete an event from Google Calendar.

        Args:
            event_id: The event ID to delete.

        Raises:
            CalendarAPIError: If event not found (404) or API call fails.
            CalendarAuthError: If not authenticated.
        """
        service = await self._get_service()
        request_id = new_request_id()
        self._logger.info(f"Deleting event: {event_id}", extra={"request_id": request_id})

        def _delete():
            return service.events().delete(
                calendarId=self._settings.GOOGLE_CALENDAR_ID,
                eventId=event_id,
            ).execute()

        try:
            await self._retry_with_backoff(_delete)
            self._logger.info(
                f"Event deleted successfully: {event_id}",
                extra={"request_id": request_id},
            )
        except CalendarAPIError as e:
            if "Event not found" in str(e):
                self._logger.error(
                    f"Event not found: {event_id}",
                    extra={"request_id": request_id},
                )
            else:
                self._logger.error(
                    f"Failed to delete event {event_id}: {e}",
                    extra={"request_id": request_id},
                )
            raise

    def _convert_utc_to_user_tz(self, utc_dt: datetime) -> datetime:
        """Convert UTC datetime to user timezone.

        Args:
            utc_dt: UTC datetime (naive or aware). Naive is assumed UTC.

        Returns:
            Datetime in user timezone (aware).
        """
        user_tz = ZoneInfo(str(self._settings.TIMEZONE))
        # If naive, assume UTC
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=UTC)
        return utc_dt.astimezone(user_tz)

    def _convert_user_tz_to_utc(self, user_dt: datetime) -> datetime:
        """Convert user timezone datetime to UTC.

        Args:
            user_dt: User TZ datetime (naive or aware). Naive is assumed user TZ.

        Returns:
            Datetime in UTC (aware).
        """
        user_tz = ZoneInfo(str(self._settings.TIMEZONE))
        # If naive, assume user TZ
        if user_dt.tzinfo is None:
            user_dt = user_dt.replace(tzinfo=user_tz)
        return user_dt.astimezone(UTC)

    def _format_for_display(self, utc_dt: datetime) -> str:
        """Format UTC datetime for display in user timezone.

        Args:
            utc_dt: UTC datetime (aware).

        Returns:
            Formatted string like "HH:MM Europe/Moscow".
        """
        user_tz_name = str(self._settings.TIMEZONE)
        user_dt = self._convert_utc_to_user_tz(utc_dt)
        return f"{user_dt:%H:%M} {user_tz_name}"

    async def find_available_slots(
        self,
        date: datetime,
        duration_minutes: int = 60,
        max_slots: int = 3,
        working_hours: tuple[int, int] = (9, 18),
    ) -> list[dict]:
        """Find available time slots in the calendar for a given date.

        Args:
            date: Date to search for slots (used with working_hours to define window).
            duration_minutes: Duration of each slot in minutes.
            max_slots: Maximum number of slots to return.
            working_hours: Tuple of (start_hour, end_hour) in user timezone.

        Returns:
            List of dicts with keys: start, end (UTC datetimes),
            start_display, end_display (formatted strings).
            Empty list on API failure after retries.
        """
        request_id = new_request_id()
        user_tz = ZoneInfo(str(self._settings.TIMEZONE))

        try:
            # Build working window in user TZ
            if date.tzinfo is None:
                date = date.replace(tzinfo=user_tz)
            else:
                date = date.astimezone(user_tz)

            window_start = date.replace(hour=working_hours[0], minute=0, second=0, microsecond=0)
            window_end = date.replace(hour=working_hours[1], minute=0, second=0, microsecond=0)

            # Convert to UTC for API call
            time_min_utc = self._convert_user_tz_to_utc(window_start)
            time_max_utc = self._convert_user_tz_to_utc(window_end)

            # Format for Google Calendar API (RFC3339)
            time_min_str = time_min_utc.isoformat().replace("+00:00", "Z")
            time_max_str = time_max_utc.isoformat().replace("+00:00", "Z")

            service = await self._get_service()

            events_list = []

            def _list_events():
                return (
                    service.events()
                    .list(
                        calendarId=self._settings.GOOGLE_CALENDAR_ID,
                        timeMin=time_min_str,
                        timeMax=time_max_str,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

            result = await self._retry_with_backoff(_list_events)
            events_list = result.get("items", [])

            # Parse events into intervals (clamped to working window)
            busy_intervals = []
            for event in events_list:
                start_raw = event.get("start", {})
                end_raw = event.get("end", {})

                # Skip all-day events (no dateTime key)
                if "dateTime" not in start_raw or "dateTime" not in end_raw:
                    self._logger.debug(
                        "Skipping all-day event",
                        extra={"request_id": request_id, "event_id": event.get("id")},
                    )
                    continue

                # Parse datetimes (may have Z or offset)
                event_start = datetime.fromisoformat(start_raw["dateTime"].replace("Z", "+00:00"))
                event_end = datetime.fromisoformat(end_raw["dateTime"].replace("Z", "+00:00"))

                # Convert to UTC if needed
                if event_start.tzinfo is not None:
                    event_start = event_start.astimezone(UTC)
                if event_end.tzinfo is not None:
                    event_end = event_end.astimezone(UTC)

                # Clamp to working window
                clamped_start = max(event_start, time_min_utc)
                clamped_end = min(event_end, time_max_utc)

                if clamped_start < clamped_end:
                    busy_intervals.append((clamped_start, clamped_end))

            # Merge overlapping intervals
            if busy_intervals:
                busy_intervals.sort(key=lambda x: x[0])
                merged = [busy_intervals[0]]
                for current_start, current_end in busy_intervals[1:]:
                    last_start, last_end = merged[-1]
                    if current_start <= last_end:
                        # Overlapping - merge
                        merged[-1] = (last_start, max(last_end, current_end))
                    else:
                        merged.append((current_start, current_end))
                busy_intervals = merged

            # Find free slots
            free_slots = []
            current_time = time_min_utc
            duration_td = timedelta(minutes=duration_minutes)

            for busy_start, busy_end in busy_intervals:
                # Gap before this busy interval
                while current_time + duration_td <= busy_start and len(free_slots) < max_slots:
                    slot_end = current_time + duration_td
                    free_slots.append(
                        {
                            "start": current_time,
                            "end": slot_end,
                            "start_display": self._format_for_display(current_time),
                            "end_display": self._format_for_display(slot_end),
                        }
                    )
                    current_time = slot_end

                # Move past this busy interval
                current_time = max(current_time, busy_end)

            # After last busy interval, fill remaining slots
            while current_time + duration_td <= time_max_utc and len(free_slots) < max_slots:
                slot_end = current_time + duration_td
                free_slots.append(
                    {
                        "start": current_time,
                        "end": slot_end,
                        "start_display": self._format_for_display(current_time),
                        "end_display": self._format_for_display(slot_end),
                    }
                )
                current_time = slot_end

            self._logger.info(
                f"Found {len(free_slots)} available slots",
                extra={"request_id": request_id},
            )
            return free_slots

        except CalendarAPIError as e:
            self._logger.warning(
                f"Failed to find available slots: {e}",
                extra={"request_id": request_id},
            )
            return []
        except Exception as e:
            self._logger.warning(
                f"Unexpected error finding available slots: {e}",
                extra={"request_id": request_id},
            )
            return []

    async def get_upcoming_events(
        self, time_min: datetime, time_max: datetime
    ) -> list[dict]:
        """Получить события в окне [time_min, time_max].

        Args:
            time_min: Начало окна (aware UTC datetime).
            time_max: Конец окна (aware UTC datetime).

        Returns:
            Список событий с ключами:
            - id: str (event ID)
            - title: str (summary)
            - start_time: datetime (aware UTC)
            - end_time: datetime (aware UTC)
            - description: str | None
            - location: str | None
            
            All-day события (нет dateTime в start/end) пропускаются с debug-логом.

        Raises:
            CalendarAuthError: Если не аутентифицирован.
            CalendarAPIError: Если API-вызов не удался после retry.
        """
        request_id = new_request_id()
        
        # Убедиться, что datetime aware UTC
        if time_min.tzinfo is None:
            time_min = time_min.replace(tzinfo=timezone.utc)
        if time_max.tzinfo is None:
            time_max = time_max.replace(tzinfo=timezone.utc)
        
        # Формат RFC3339 для Google Calendar API
        time_min_str = time_min.isoformat().replace("+00:00", "Z")
        time_max_str = time_max.isoformat().replace("+00:00", "Z")
        
        service = await self._get_service()
        
        def _list_events():
            return (
                service.events()
                .list(
                    calendarId=self._settings.GOOGLE_CALENDAR_ID,
                    timeMin=time_min_str,
                    timeMax=time_max_str,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        
        try:
            result = await self._retry_with_backoff(_list_events)
            items = result.get("items", [])
            
            events = []
            for item in items:
                start_raw = item.get("start", {})
                end_raw = item.get("end", {})
                
                # Пропустить all-day события
                if "dateTime" not in start_raw or "dateTime" not in end_raw:
                    self._logger.debug(
                        "Skipping all-day event",
                        extra={"request_id": request_id, "event_id": item.get("id")},
                    )
                    continue
                
                # Парсинг datetime
                start_dt = datetime.fromisoformat(start_raw["dateTime"].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_raw["dateTime"].replace("Z", "+00:00"))
                
                # Конвертация в UTC
                if start_dt.tzinfo is not None:
                    start_dt = start_dt.astimezone(timezone.utc)
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.astimezone(timezone.utc)
                
                events.append({
                    "id": item.get("id"),
                    "title": item.get("summary", ""),
                    "start_time": start_dt,
                    "end_time": end_dt,
                    "description": item.get("description"),
                    "location": item.get("location"),
                })
            
            self._logger.info(
                f"Retrieved {len(events)} upcoming events",
                extra={"request_id": request_id},
            )
            return events
        
        except CalendarAPIError as e:
            self._logger.error(
                f"Failed to get upcoming events: {e}",
                extra={"request_id": request_id},
            )
            raise
