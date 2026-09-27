"""Execute exactly one owned, approved Calendar action with crash reconciliation."""
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from postgrest.exceptions import APIError

from focusos_api.approval_preflight import (ApprovalPreflightUnavailable, ApprovalStale,
    check_approval_preflight, load_approval)
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.calendar_write import (CalendarWriteConflict, CalendarWriteDeferred,
    CalendarWriteExpired, CalendarWriteReconnect, CalendarWriteRejected, CalendarWriteUnknown,
    insert_or_reconcile)
from focusos_api.database import DatabaseUnavailable, scoped_client, service_client
from focusos_api.google_token_store import SupabaseGoogleTokenStore
from focusos_api.google_tokens import (GoogleOAuthClient, GoogleReconnectRequired,
    GoogleRefreshInProgress, GoogleTokenError, GoogleTokenProviderUnavailable,
    get_google_access_token)
from focusos_api.token_crypto import TokenCipher, TokenCipherError


def _service_rpc(name: str, params: dict) -> object:
    try:
        with service_client() as client:
            return client.rpc(name, params).execute().data
    except APIError as exc:
        raise DatabaseUnavailable("Approval execution database operation failed") from exc


def _get_bearer(connection_id: UUID) -> str:
    cipher = TokenCipher.from_environment()
    oauth = GoogleOAuthClient.from_environment()
    return get_google_access_token(connection_id, SupabaseGoogleTokenStore(), cipher, oauth)


def execute_approval(access_token: str, approval_id: UUID) -> ApprovalRecord:
    # Verify the JWT before using a privileged RPC. SQL also checks this owner ID.
    with scoped_client(access_token) as (user_id, _):
        pass
    before = load_approval(access_token, approval_id)
    claim = _service_rpc("focusos_claim_approval_execution", {
        "p_user_id": user_id, "p_approval_id": str(approval_id),
    })
    if not isinstance(claim, dict) or not isinstance(claim.get("approval"), dict):
        raise DatabaseUnavailable("Approval claim unavailable")
    try:
        approval = ApprovalRecord.model_validate(claim["approval"])
    except ValidationError as exc:
        raise DatabaseUnavailable("Approval claim invalid") from exc
    if approval.id != approval_id:
        raise DatabaseUnavailable("Approval claim identity mismatch")
    if claim.get("claimed") is not True:
        return approval
    # Only the invocation that received claimed=true may call Google.
    result_status, event_id, link, code = "unknown", None, None, "unexpected_failure"
    try:
        bearer = _get_bearer(approval.connection_id)
        recovered = before.status in ("executing", "unknown")
        outcome = insert_or_reconcile(approval, bearer,
            preflight=lambda: check_approval_preflight(access_token, approval),
            allow_insert=approval.expires_at>datetime.now(timezone.utc))
        result_status, event_id, link, code = "succeeded", outcome.event_id, outcome.link, None
    except CalendarWriteExpired:
        result_status, code = "stale", "approval_expired"
    except ApprovalStale as exc:
        result_status, code = ("unknown" if recovered and exc.code=="slot_conflict" else "stale"), exc.code
    except (CalendarWriteReconnect, GoogleReconnectRequired):
        result_status, code = "stale", "calendar_reconnect_required"
    except (ApprovalPreflightUnavailable, GoogleRefreshInProgress, GoogleTokenProviderUnavailable,
            GoogleTokenError, TokenCipherError, DatabaseUnavailable):
        result_status, code = "approved", "preflight_or_token_unavailable"
    except CalendarWriteDeferred:
        result_status, code = "unknown", "calendar_rate_limited"
    except CalendarWriteConflict:
        result_status, code = "failed", "provider_event_conflict"
    except CalendarWriteRejected:
        result_status, code = "failed", "provider_rejected"
    except CalendarWriteUnknown:
        result_status, code = "unknown", "provider_outcome_unknown"
    finished = _service_rpc("focusos_finish_approval_execution", {
        "p_user_id": user_id, "p_approval_id": str(approval_id),
        "p_expected_version": approval.status_version, "p_status": result_status,
        "p_provider_event_id": event_id, "p_provider_link": link,
        "p_safe_code": code,
    })
    if finished is not True:
        raise DatabaseUnavailable("Approval execution checkpoint lost")
    return load_approval(access_token, approval_id)
