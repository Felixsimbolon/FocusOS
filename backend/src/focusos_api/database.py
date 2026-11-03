"""User-scoped Supabase access for the FocusOS API."""

import base64
import hashlib
import json
import os
import threading
import time
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


# One request makes many database operations (and a job step its retries); Supabase Auth is asked once per session per
# minute instead of once per operation. PostgREST still checks every JWT's signature and expiry itself.
SESSION_TTL_SECONDS = 60
MAX_VERIFIED_SESSIONS = 512
_verified: dict[str, tuple[str, float]] = {}  # sha256(token) -> (user id, wall-clock expiry)
_verified_lock = threading.Lock()


def _token_key(access_token: str) -> str:
    return hashlib.sha256(access_token.encode()).hexdigest()


def _token_expiry(access_token: str) -> float | None:
    """The JWT's own exp claim, read only to cap how long its verification is remembered (never trusted as proof)."""
    try:
        payload = access_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(claims["exp"]) if isinstance(claims, dict) and isinstance(claims.get("exp"), (int, float)) else None
    except (IndexError, ValueError, KeyError, TypeError):
        return None


def _verified_user(access_token: str) -> str | None:
    key, now = _token_key(access_token), time.time()
    with _verified_lock:
        entry = _verified.get(key)
        if entry and entry[1] > now:
            return entry[0]
        _verified.pop(key, None)
    return None


def _remember(access_token: str, user_id: str) -> None:
    now = time.time()
    expiry = min(now + SESSION_TTL_SECONDS, _token_expiry(access_token) or now + SESSION_TTL_SECONDS)
    if expiry <= now:
        return
    with _verified_lock:
        if len(_verified) >= MAX_VERIFIED_SESSIONS:
            for key in [key for key, (_, until) in _verified.items() if until <= now] or list(_verified)[: MAX_VERIFIED_SESSIONS // 4]:
                _verified.pop(key, None)
        _verified[_token_key(access_token)] = (user_id, expiry)


def forget_verified_sessions() -> None:
    with _verified_lock:
        _verified.clear()


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
            user_id = _verified_user(access_token)
            if user_id is None:
                user = supabase.auth.get_user(access_token).user
                if user is None:
                    raise InvalidSession()
                user_id = str(user.id)
                _remember(access_token, user_id)

            supabase.postgrest.auth(access_token)
            yield user_id, supabase
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


@contextmanager
def service_client() -> Iterator[Client]:
    """Create a fresh server-only client for narrowly scoped privileged RPCs."""
    url = os.environ.get("FOCUSOS_SUPABASE_URL", "").strip()
    service_key = os.environ.get("FOCUSOS_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not service_key.startswith("sb_secret_"):
        raise DatabaseUnavailable("Server-only Supabase credential settings are missing")

    try:
        with httpx.Client(timeout=10.0) as transport:
            client = create_client(
                url,
                service_key,
                options=ClientOptions(
                    httpx_client=transport,
                    auto_refresh_token=False,
                    persist_session=False,
                ),
            )
            yield client
    except (APIError, httpx.HTTPError) as exc:
        raise DatabaseUnavailable("Privileged database operation failed") from exc
