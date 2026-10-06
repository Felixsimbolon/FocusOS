"""Cancel only a stored FocusOS event, using its marker and an ETag precondition."""
from uuid import UUID
import httpx
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.approval_execute import _get_bearer
from focusos_api.calendar_write import _verify_event, _event_url, CalendarWriteConflict
from focusos_api.connections import read_google_connection
from focusos_api.google_oauth import GOOGLE_CALENDAR_WRITE_SCOPE
from focusos_api.database import DatabaseUnavailable, scoped_client

class CancellationUnavailable(Exception): pass

def delete_owned_event(approval: ApprovalRecord, bearer: str, *, client: httpx.Client | None = None) -> str:
    if approval.status != "succeeded" or approval.calendar_id != "primary": raise CancellationUnavailable()
    own=client is None
    transport=client or httpx.Client(timeout=10, follow_redirects=False)
    headers={"Authorization":"Bearer "+bearer}
    url=_event_url(approval.event_id)
    try:
        response=transport.get(url, headers=headers, params={"fields":"id,etag,summary,status,start,end,attendees,extendedProperties,htmlLink"})
        if response.status_code in (404,410): return "cancelled"
        if response.status_code != 200 or len(response.content)>32768: return "unknown"
        event=response.json()
        if event.get("status")=="cancelled": return "cancelled"
        try: _verify_event(event,approval,reconciled=True)
        except CalendarWriteConflict: return "changed"
        etag=event.get("etag")
        if not isinstance(etag,str) or not etag or len(etag)>256 or any(ord(c)<32 or ord(c)>126 for c in etag): return "unknown"
        response=transport.delete(url,headers={**headers,"If-Match":etag},params={"sendUpdates":"none"})
        if response.status_code in (204,404,410): return "cancelled"
        if response.status_code==412: return "changed"
        return "unknown"
    except (httpx.HTTPError,ValueError,TypeError,AttributeError):
        # An interrupted DELETE may have succeeded; retry always reads the same stable event ID first.
        return "unknown"
    finally:
        if own: transport.close()


def cancel_focus_block(token: str, action_id: UUID) -> dict:
    with scoped_client(token) as (_,client):
        claim=client.rpc("focusos_claim_calendar_cancellation",{"p_id":str(action_id)}).execute().data
    if not isinstance(claim,dict): raise CancellationUnavailable()
    if claim.get("claimed") is not True: return {"status":claim.get("status","unknown")}
    approval=ApprovalRecord.model_validate(claim["approval"])
    if approval.id != action_id: raise DatabaseUnavailable("Cancellation identity mismatch")
    status,code="unknown","provider_unavailable"
    try:
        connection=read_google_connection(token)
        if connection is None or connection.id!=approval.connection_id or connection.status!="connected" or GOOGLE_CALENDAR_WRITE_SCOPE not in connection.granted_scopes:
            code="calendar_reconnect_required"
        else:
            status=delete_owned_event(approval,_get_bearer(approval.connection_id))
            code=None if status=="cancelled" else "provider_event_changed" if status=="changed" else "provider_outcome_unknown"
    except Exception:
        pass # No provider body, credentials, or event details in errors.
    with scoped_client(token) as (_,client):
        saved=client.rpc("focusos_finish_calendar_cancellation",{"p_id":str(action_id),"p_lease":claim["lease"],"p_status":status,"p_error":code}).execute().data
    if saved is not True: raise DatabaseUnavailable("Cancellation checkpoint lost")
    return {"status":status,"safe_error":code}
