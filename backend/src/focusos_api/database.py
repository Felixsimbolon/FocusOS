"""User-scoped Supabase access for the FocusOS API."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from postgrest.exceptions import APIError
from supabase import Client, create_client
from supabase.client import ClientOptions
from supabase_auth.errors import AuthError


class InvalidSession(Exception):
    """The caller did not provide a valid Supabase Auth access token."""


class DatabaseUnavailable(Exception):
    """A restricted database operation could not be completed."""


def _settings() -> tuple[str, str]:
    url = os.environ.get("FOCUSOS_SUPABASE_URL", "").strip()
    publishable_key = os.environ.get("FOCUSOS_SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not publishable_key:
        raise DatabaseUnavailable("Supabase database settings are missing")
    if not publishable_key.startswith("sb_publishable_"):
        raise DatabaseUnavailable("A Supabase publishable key is required")
    return url, publishable_key


@contextmanager
def scoped_client(access_token: str) -> Iterator[tuple[str, Client]]:
    """Verify Auth and use the caller's JWT for one PostgREST operation."""
    if not access_token:
        raise InvalidSession()

    url, publishable_key = _settings()
    try:
        # Fresh clients and transports keep user credentials out of shared state.
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
            yield str(user.id), supabase
    except AuthError as exc:
        raise InvalidSession() from exc
    except (APIError, httpx.HTTPError) as exc:
        raise DatabaseUnavailable("Restricted database operation failed") from exc


def check_database_identity(access_token: str) -> None:
    """Confirm that Auth and PostgREST see the same verified user."""
    with scoped_client(access_token) as (user_id, supabase):
        database_user_id = supabase.rpc("focusos_session_uid", get=True).execute().data

    if str(database_user_id) != user_id:
        raise DatabaseUnavailable("Database identity did not match Auth identity")
