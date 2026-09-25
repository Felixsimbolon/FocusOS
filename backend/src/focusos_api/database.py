"""A user-scoped, read-only Supabase database connectivity check."""

import os

import httpx
from postgrest.exceptions import APIError
from supabase import create_client
from supabase.client import ClientOptions
from supabase_auth.errors import AuthError


class InvalidSession(Exception):
    """The caller did not provide a valid Supabase Auth access token."""


class DatabaseUnavailable(Exception):
    """The restricted database check could not be completed."""


def _settings() -> tuple[str, str]:
    url = os.environ.get("FOCUSOS_SUPABASE_URL", "").strip()
    publishable_key = os.environ.get("FOCUSOS_SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not publishable_key:
        raise DatabaseUnavailable("Supabase database settings are missing")
    if not publishable_key.startswith("sb_publishable_"):
        raise DatabaseUnavailable("A Supabase publishable key is required")
    return url, publishable_key


def check_database_identity(access_token: str) -> None:
    """Confirm that Auth and PostgREST see the same verified user."""
    if not access_token:
        raise InvalidSession()

    url, publishable_key = _settings()

    try:
        # A fresh client and HTTP transport prevent credentials crossing requests.
        with httpx.Client(timeout=10.0) as transport:
            supabase = create_client(
                url,
                publishable_key,
                options=ClientOptions(
                    httpx_client=transport,
                    auto_refresh_token=False,
                    persist_session=False,
                ),
            )
            user = supabase.auth.get_user(access_token).user
            if user is None:
                raise InvalidSession()

            supabase.postgrest.auth(access_token)
            database_user_id = supabase.rpc(
                "focusos_session_uid", get=True
            ).execute().data
    except AuthError as exc:
        raise InvalidSession() from exc
    except (APIError, httpx.HTTPError) as exc:
        raise DatabaseUnavailable("Restricted database check failed") from exc

    if str(database_user_id) != str(user.id):
        raise DatabaseUnavailable("Database identity did not match Auth identity")
