"""Read a bounded page from the user's primary Google Calendar without mutation."""

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable
from focusos_api.google_token_store import SupabaseGoogleTokenStore
from focusos_api.google_tokens import (
    GoogleOAuthClient,
    GoogleReconnectRequired,
    GoogleRefreshInProgress,
    GoogleTokenError,
    GoogleTokenProviderUnavailable,
    get_google_access_token,
)
from focusos_api.token_crypto import TokenCipher, TokenCipherError

CALENDAR_EVENTS_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned.readonly"
PAGE_SIZE = 10
WINDOW_DAYS = 7


class CalendarProbeError(Exception):
    """A safe Calendar read failure."""


class CalendarProbeUnavailable(CalendarProbeError):
    """Provider or token storage is temporarily unavailable."""


class CalendarReconnectRequired(CalendarProbeError):
    """The Google grant must be authorized again."""


class CalendarPageProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar: str = "primary"
    window_start: datetime
    window_end: datetime
    event_count: int
    page_has_more: bool


def read_primary_calendar_page(
    access_token: str,
    *,
    http_client: httpx.Client | None = None,
    now: datetime | None = None,
) -> CalendarPageProbe:
    connection = read_google_connection(access_token)
    if connection is None or connection.status != "connected":
        raise CalendarReconnectRequired("Google connection needs authorization")
    if CALENDAR_READ_SCOPE not in connection.granted_scopes:
        raise CalendarReconnectRequired("Calendar read permission is missing")

    try:
        cipher = TokenCipher.from_environment()
        oauth_client = GoogleOAuthClient.from_environment()
    except (TokenCipherError, GoogleTokenError) as exc:
        raise CalendarProbeUnavailable("Google token configuration is unavailable") from exc

    try:
        bearer = get_google_access_token(
            connection.id, SupabaseGoogleTokenStore(), cipher, oauth_client
        )
    except GoogleReconnectRequired as exc:
        raise CalendarReconnectRequired("Google connection needs authorization") from exc
    except GoogleRefreshInProgress as exc:
        raise CalendarProbeUnavailable("Google token refresh is already in progress") from exc
    except (GoogleTokenProviderUnavailable, DatabaseUnavailable, GoogleTokenError) as exc:
        raise CalendarProbeUnavailable("Google token is temporarily unavailable") from exc

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise CalendarProbeError("Calendar probe time must include a timezone")
    current = current.astimezone(timezone.utc)
    end = current + timedelta(days=WINDOW_DAYS)
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        try:
            response = client.get(
                CALENDAR_EVENTS_API,
                params={
                    "timeMin": current.isoformat().replace("+00:00", "Z"),
                    "timeMax": end.isoformat().replace("+00:00", "Z"),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": PAGE_SIZE,
                },
                headers={"Authorization": "Bearer " + bearer},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise CalendarProbeUnavailable("Google Calendar is temporarily unavailable") from exc
        if response.status_code == 401:
            raise CalendarReconnectRequired("Google connection needs authorization")
        if response.status_code != 200:
            raise CalendarProbeError("Google Calendar could not read the primary calendar")
        try:
            result: Any = response.json()
        except ValueError as exc:
            raise CalendarProbeError("Google Calendar returned an invalid response") from exc
        if not isinstance(result, dict):
            raise CalendarProbeError("Google Calendar returned an invalid response")
        events = result.get("items", [])
        if not isinstance(events, list) or len(events) > PAGE_SIZE:
            raise CalendarProbeError("Google Calendar returned invalid event metadata")
        return CalendarPageProbe(
            window_start=current,
            window_end=end,
            event_count=len(events),
            page_has_more=isinstance(result.get("nextPageToken"), str),
        )
    finally:
        if own_client:
            client.close()
