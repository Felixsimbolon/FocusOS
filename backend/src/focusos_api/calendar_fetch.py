"""Complete bounded read of the user's primary Google Calendar."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict

from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable
from focusos_api.google_calendar import CALENDAR_EVENTS_API, CALENDAR_READ_SCOPE, CalendarReconnectRequired
from focusos_api.google_token_store import SupabaseGoogleTokenStore
from focusos_api.google_tokens import (
    GoogleOAuthClient, GoogleReconnectRequired, GoogleRefreshInProgress,
    GoogleTokenError, GoogleTokenProviderUnavailable, get_google_access_token,
)
from focusos_api.token_crypto import TokenCipher, TokenCipherError

MAX_WINDOW_SECONDS = 14 * 86400
PAGE_SIZE = 100
MAX_PAGES = 5
MAX_EVENTS = PAGE_SIZE * MAX_PAGES


class CalendarFetchError(Exception):
    """Invalid or incomplete provider read; no free slots may be calculated."""


class CalendarFetchUnavailable(CalendarFetchError):
    """A retryable provider or server configuration failure."""


@dataclass(frozen=True)
class CalendarWindow:
    start: datetime
    end: datetime
    fetched_at: datetime
    calendar_id: str
    calendar_timezone: str
    events: tuple[dict[str, Any], ...]
    complete: bool = True


class CalendarWindowStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar: str
    timezone: str
    window_start: datetime
    window_end: datetime
    fetched_at: datetime
    event_count: int
    complete: bool = True


def _validate_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise CalendarFetchError("Calendar window requires timezone offsets")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    seconds = (end - start).total_seconds()
    if seconds <= 0 or seconds > MAX_WINDOW_SECONDS:
        raise CalendarFetchError("Calendar window must be positive and at most 14 days")
    return start, end


def _bearer(access_token: str) -> str:
    connection = read_google_connection(access_token)
    if connection is None or connection.status != "connected" or CALENDAR_READ_SCOPE not in connection.granted_scopes:
        raise CalendarReconnectRequired("Connect Google with Calendar read access")
    try:
        cipher = TokenCipher.from_environment()
        oauth_client = GoogleOAuthClient.from_environment()
        return get_google_access_token(connection.id, SupabaseGoogleTokenStore(), cipher, oauth_client)
    except GoogleReconnectRequired as exc:
        raise CalendarReconnectRequired("Reconnect Google") from exc
    except (GoogleRefreshInProgress, GoogleTokenProviderUnavailable, GoogleTokenError,
            TokenCipherError, DatabaseUnavailable) as exc:
        raise CalendarFetchUnavailable("Calendar credential temporarily unavailable") from exc


def fetch_calendar_window(access_token: str, start: datetime, end: datetime, *,
                          http_client: httpx.Client | None = None,
                          bearer: str | None = None,
                          observed_at: datetime | None = None) -> CalendarWindow:
    start, end = _validate_window(start, end)
    token = bearer if bearer is not None else _bearer(access_token)
    fetched = observed_at or datetime.now(timezone.utc)
    if fetched.tzinfo is None:
        raise CalendarFetchError("Observation time requires timezone")
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=6.0, follow_redirects=False)
    events: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    page_token: str | None = None
    calendar_timezone: str | None = None
    try:
        for page_number in range(MAX_PAGES):
            params = {
                "timeMin": start.isoformat().replace("+00:00", "Z"),
                "timeMax": end.isoformat().replace("+00:00", "Z"),
                "singleEvents": "true", "orderBy": "startTime",
                "maxResults": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                response = client.get(CALENDAR_EVENTS_API, params=params,
                                      headers={"Authorization": "Bearer " + token}, timeout=6.0)
            except httpx.HTTPError as exc:
                raise CalendarFetchUnavailable("Google Calendar read interrupted") from exc
            if response.status_code in (401, 403):
                raise CalendarReconnectRequired("Reconnect Google with Calendar read access")
            if response.status_code != 200:
                raise CalendarFetchUnavailable("Google Calendar read interrupted")
            try:
                data = response.json()
            except ValueError as exc:
                raise CalendarFetchError("Invalid Calendar response") from exc
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise CalendarFetchError("Invalid Calendar page")
            items = data["items"]
            if len(items) > PAGE_SIZE or any(not isinstance(item, dict) for item in items):
                raise CalendarFetchError("Invalid Calendar event page")
            zone = data.get("timeZone")
            if not isinstance(zone, str):
                raise CalendarFetchError("Calendar timezone missing")
            try:
                ZoneInfo(zone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise CalendarFetchError("Invalid Calendar timezone") from exc
            if calendar_timezone is not None and zone != calendar_timezone:
                raise CalendarFetchError("Calendar timezone changed between pages")
            calendar_timezone = zone
            events.extend(items)
            if len(events) > MAX_EVENTS:
                raise CalendarFetchError("Calendar window exceeds safe event limit")
            next_token = data.get("nextPageToken")
            if next_token is None:
                return CalendarWindow(start, end, fetched.astimezone(timezone.utc),
                                      "primary", calendar_timezone, tuple(events))
            if not isinstance(next_token, str) or not next_token or len(next_token) > 4096:
                raise CalendarFetchError("Invalid Calendar page token")
            if next_token in seen_tokens or next_token == page_token:
                raise CalendarFetchError("Calendar page token repeated")
            seen_tokens.add(next_token)
            page_token = next_token
        raise CalendarFetchError("Calendar window exceeds safe page limit")
    finally:
        if own_client:
            client.close()


def calendar_window_status(window: CalendarWindow) -> CalendarWindowStatus:
    return CalendarWindowStatus(calendar=window.calendar_id, timezone=window.calendar_timezone,
        window_start=window.start, window_end=window.end, fetched_at=window.fetched_at,
        event_count=len(window.events))

