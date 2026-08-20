"""Tests for calendar_service module."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError

from app.config import get_settings
from app.services.calendar_service import CalendarAuthError, CalendarService


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Clean environment variables and clear settings cache before each test.

    This fixture ensures tests don't depend on local .env files.
    """
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TEMPERATURE_CLASSIFICATION",
        "LLM_TEMPERATURE_REMINDER",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_ANALYSIS",
        "LLM_TIMEOUT_CLASSIFICATION",
        "LLM_TIMEOUT_REMINDER",
        "LLM_RATE_LIMIT_RPM",
        "LLM_RATE_LIMIT_TPM",
        "LLM_MAX_RETRIES",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "DIGEST_TIME_HOUR",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_WINDOW_HOURS",
        "REMINDER_LOOKAHEAD_MINUTES",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
        "USER_TIMEZONE",
        "TIMEZONE",
        "LOG_LEVEL",
        "LOG_FILE",
        "NEWS_LOOKBACK_HOURS",
        "NEWS_DEDUP_WINDOW_DAYS",
        "NEWS_BATCH_MIN",
        "NEWS_BATCH_MAX",
        "NEWS_DELIVERY_RETRIES",
        "NEWS_DELIVERY_RETRY_DELAY_MINUTES",
        "FETCH_TIMEOUT_SECONDS",
        "FETCH_MAX_RETRIES",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    # Set baseline required values
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    """Create mock settings with temp paths for token/credentials files."""
    credentials_file = tmp_path / "google_credentials.json"
    token_file = tmp_path / "google_token.json"

    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(credentials_file))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "primary")

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def valid_token_data():
    """Return valid token data structure."""
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    return {
        "token": "valid_access_token",
        "refresh_token": "valid_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id.apps.googleusercontent.com",
        "client_secret": "test_client_secret",
        "scopes": ["https://www.googleapis.com/auth/calendar.events.readwrite"],
        "expiry": expiry.isoformat(),
    }


@pytest.fixture
def expired_token_data():
    """Return expired token data structure."""
    expiry = datetime.now(timezone.utc) - timedelta(hours=1)
    return {
        "token": "expired_access_token",
        "refresh_token": "valid_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id.apps.googleusercontent.com",
        "client_secret": "test_client_secret",
        "scopes": ["https://www.googleapis.com/auth/calendar.events.readwrite"],
        "expiry": expiry.isoformat(),
    }


class TestCalendarAuthError:
    """Test CalendarAuthError exception."""

    def test_calendar_auth_error_is_runtime_error(self):
        """Test CalendarAuthError is a subclass of RuntimeError."""
        assert issubclass(CalendarAuthError, RuntimeError)

    def test_calendar_auth_error_message(self):
        """Test CalendarAuthError accepts message."""
        error = CalendarAuthError("Test error message")
        assert str(error) == "Test error message"


class TestCalendarServiceInit:
    """Test CalendarService initialization."""

    def test_init_with_default_settings(self, mock_settings):
        """Test initialization uses get_settings() by default."""
        service = CalendarService()
        assert service._settings is not None

    def test_init_with_custom_settings(self, mock_settings):
        """Test initialization accepts custom settings."""
        custom_settings = mock_settings
        service = CalendarService(settings=custom_settings)
        assert service._settings is custom_settings

    def test_init_initializes_credentials_none(self, mock_settings):
        """Test credentials is None after init."""
        service = CalendarService(settings=mock_settings)
        assert service._credentials is None

    def test_init_initializes_service_none(self, mock_settings):
        """Test service is None after init."""
        service = CalendarService(settings=mock_settings)
        assert service._service is None


class TestLoadCredentialsFromFile:
    """Test _load_credentials_from_file method."""

    def test_load_credentials_success(self, mock_settings, valid_token_data):
        """Test successful credential loading from file."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps(valid_token_data))

        service = CalendarService(settings=mock_settings)
        credentials = service._load_credentials_from_file()

        assert credentials is not None
        assert credentials.token == "valid_access_token"

    def test_load_credentials_file_not_found(self, mock_settings):
        """Test error when token file doesn't exist."""
        service = CalendarService(settings=mock_settings)

        with pytest.raises(CalendarAuthError) as exc_info:
            service._load_credentials_from_file()

        assert "Token file not found" in str(exc_info.value)

    def test_load_credentials_invalid_json(self, mock_settings, tmp_path):
        """Test error when JSON is invalid."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text("not valid json")

        service = CalendarService(settings=mock_settings)

        with pytest.raises(CalendarAuthError) as exc_info:
            service._load_credentials_from_file()

        assert "Invalid JSON" in str(exc_info.value)

    def test_load_credentials_missing_fields(self, mock_settings, tmp_path):
        """Test error when credentials JSON is missing required fields."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text('{"token": "only_token"}')

        service = CalendarService(settings=mock_settings)

        with pytest.raises(CalendarAuthError) as exc_info:
            service._load_credentials_from_file()

        assert "Failed to parse credentials" in str(exc_info.value)


class TestRefreshToken:
    """Test _refresh_token method."""

    def test_refresh_token_success(self, mock_settings, valid_token_data):
        """Test successful token refresh."""
        service = CalendarService(settings=mock_settings)

        mock_credentials = MagicMock()
        mock_credentials.valid = True
        mock_credentials.refresh_token = "refresh_token"

        with patch.object(
            mock_credentials, "refresh", return_value=None
        ) as mock_refresh:
            result = service._refresh_token(mock_credentials)
            mock_refresh.assert_called_once()
            assert result is mock_credentials

    def test_refresh_token_raises_refresh_error(self, mock_settings):
        """Test error when refresh fails."""
        service = CalendarService(settings=mock_settings)

        mock_credentials = MagicMock()
        mock_credentials.refresh.side_effect = RefreshError("Refresh failed")

        with pytest.raises(CalendarAuthError) as exc_info:
            service._refresh_token(mock_credentials)

        assert "Token refresh failed" in str(exc_info.value)

    def test_refresh_token_invalid_after_refresh(self, mock_settings):
        """Test error when credentials still invalid after refresh."""
        service = CalendarService(settings=mock_settings)

        mock_credentials = MagicMock()
        mock_credentials.valid = False
        mock_credentials.refresh_token = "refresh_token"

        with pytest.raises(CalendarAuthError) as exc_info:
            service._refresh_token(mock_credentials)

        assert "did not produce valid credentials" in str(exc_info.value)


class TestSaveToken:
    """Test _save_token method."""

    def test_save_token_success(self, mock_settings, valid_token_data):
        """Test successful token saving."""
        service = CalendarService(settings=mock_settings)

        mock_credentials = MagicMock()
        mock_credentials.token = "access_token"
        mock_credentials.refresh_token = "refresh_token"
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.client_id = "client_id"
        mock_credentials.client_secret = "client_secret"
        mock_credentials.scopes = ["scope1"]
        mock_credentials.expiry = datetime.now(timezone.utc)

        service._save_token(mock_credentials)

        token_file = mock_settings.GOOGLE_TOKEN_FILE
        assert token_file.exists()

        saved_data = json.loads(token_file.read_text())
        assert saved_data["token"] == "access_token"
        assert saved_data["refresh_token"] == "refresh_token"

    def test_save_token_creates_directory(self, mock_settings, tmp_path):
        """Test that save_token creates parent directories."""
        nested_token_file = tmp_path / "nested" / "dir" / "token.json"

        mock_settings_dict = {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "GOOGLE_TOKEN_FILE": str(nested_token_file),
        }

        with patch.dict("os.environ", mock_settings_dict, clear=False):
            get_settings.cache_clear()
            settings = get_settings()
            service = CalendarService(settings=settings)

            mock_credentials = MagicMock()
            mock_credentials.token = "token"
            mock_credentials.refresh_token = "refresh"
            mock_credentials.token_uri = "uri"
            mock_credentials.client_id = "cid"
            mock_credentials.client_secret = "cs"
            mock_credentials.scopes = []
            mock_credentials.expiry = None

            service._save_token(mock_credentials)

            assert nested_token_file.exists()


class TestAuthenticate:
    """Test authenticate method."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self, mock_settings, valid_token_data):
        """Test successful authentication."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps(valid_token_data))

        service = CalendarService(settings=mock_settings)

        with patch.object(service, "_load_credentials_from_file") as mock_load:
            mock_creds = MagicMock()
            mock_creds.expired = False
            mock_creds.valid = True
            mock_creds.refresh_token = "refresh"
            mock_load.return_value = mock_creds

            with patch.object(service, "_save_token"):
                await service.authenticate()

                assert service._credentials is mock_creds

    @pytest.mark.asyncio
    async def test_authenticate_file_not_found(self, mock_settings):
        """Test authentication fails when token file not found."""
        service = CalendarService(settings=mock_settings)

        with pytest.raises(CalendarAuthError):
            await service.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_expired_token_refresh_success(
        self, mock_settings, expired_token_data
    ):
        """Test authentication with expired token that refreshes successfully."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps(expired_token_data))

        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.valid = True
        mock_creds.refresh_token = "refresh_token"

        with patch.object(service, "_load_credentials_from_file", return_value=mock_creds):
            with patch.object(service, "_refresh_token", return_value=mock_creds):
                with patch.object(service, "_save_token"):
                    await service.authenticate()

                    service._refresh_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_expired_token_refresh_fails(
        self, mock_settings, expired_token_data
    ):
        """Test authentication fails when token refresh fails."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps(expired_token_data))

        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"

        with patch.object(service, "_load_credentials_from_file", return_value=mock_creds):
            with patch.object(
                service, "_refresh_token", side_effect=CalendarAuthError("Refresh failed")
            ):
                with pytest.raises(CalendarAuthError):
                    await service.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_invalid_no_refresh_token(self, mock_settings):
        """Test authentication fails when credentials invalid and no refresh token."""
        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = False
        mock_creds.refresh_token = None

        with patch.object(service, "_load_credentials_from_file", return_value=mock_creds):
            with pytest.raises(CalendarAuthError):
                await service.authenticate()


class TestGetService:
    """Test _get_service method."""

    @pytest.mark.asyncio
    async def test_get_service_success(self, mock_settings):
        """Test successful service creation."""
        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.valid = True
        service._credentials = mock_creds

        mock_api_service = MagicMock()

        with patch(
            "app.services.calendar_service.build", return_value=mock_api_service
        ) as mock_build:
            result = await service._get_service()

            mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds)
            assert result is mock_api_service
            assert service._service is mock_api_service

    @pytest.mark.asyncio
    async def test_get_service_cached(self, mock_settings):
        """Test service is cached after first call."""
        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.valid = True
        service._credentials = mock_creds
        service._service = MagicMock()

        with patch("app.services.calendar_service.build") as mock_build:
            await service._get_service()
            mock_build.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_service_not_authenticated(self, mock_settings):
        """Test error when not authenticated."""
        service = CalendarService(settings=mock_settings)
        service._credentials = None

        with pytest.raises(CalendarAuthError) as exc_info:
            await service._get_service()

        assert "Not authenticated" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_service_invalid_credentials(self, mock_settings):
        """Test error when credentials invalid."""
        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.valid = False
        service._credentials = mock_creds

        with pytest.raises(CalendarAuthError):
            await service._get_service()


class TestAsyncOperations:
    """Test async operations use asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_authenticate_uses_async_to_thread_for_load(
        self, mock_settings, valid_token_data
    ):
        """Test that authenticate wraps file operations in asyncio.to_thread."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps(valid_token_data))

        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = True

        with patch.object(service, "_load_credentials_from_file", return_value=mock_creds):
            with patch.object(service, "_save_token"):
                await service.authenticate()

                service._load_credentials_from_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_service_uses_async_to_thread(self, mock_settings):
        """Test that _get_service wraps build in asyncio.to_thread."""
        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.valid = True
        service._credentials = mock_creds

        mock_api_service = MagicMock()

        with patch(
            "app.services.calendar_service.build", return_value=mock_api_service
        ):
            result = await service._get_service()
            assert result is mock_api_service


class TestLoggingAndRequestID:
    """Test logging and request_id binding."""

    @pytest.mark.asyncio
    async def test_authenticate_binds_request_id(self, mock_settings, valid_token_data):
        """Test that authenticate binds request_id via new_request_id()."""
        token_file = mock_settings.GOOGLE_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps(valid_token_data))

        service = CalendarService(settings=mock_settings)

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = True

        with patch.object(service, "_load_credentials_from_file", return_value=mock_creds):
            with patch.object(service, "_save_token"):
                with patch("app.services.calendar_service.new_request_id") as mock_req:
                    mock_req.return_value = "test-request-id-123"
                    await service.authenticate()

                    mock_req.assert_called_once()
