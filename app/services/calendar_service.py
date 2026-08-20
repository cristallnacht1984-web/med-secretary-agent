"""Calendar Service with OAuth2 authentication for Google Calendar API."""
import asyncio
import json
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import Settings, get_settings
from app.logging_setup import get_logger, new_request_id

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readwrite"]


class CalendarAuthError(RuntimeError):
    """Ошибка аутентификации Google Calendar."""

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
