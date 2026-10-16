# Gmail push notifications: design (not implemented)

Status: proposal, 2026-10-16. Email triage (`email_triage.py`) is implemented and runs inside the existing Sync job. Push is not, for the reasons below.

## Goal
Process a labeled email within a minute of its arrival, without the user pressing Sync.

## Why this is not a small change
Every FocusOS job today runs on behalf of a signed-in user: the job carries the user's Supabase session (15-minute limit), and every database read goes through row-level security as that user. A Gmail push arrives with no user session. It carries only the mailbox address and a `historyId`. Processing it means some server code must act for a user who is not present. That is the largest change to the security model since the job queue.

## Proposed flow
1. **Watch.** When Gmail is connected, call `users.watch` with `labelIds = [FocusOS label]` and a Pub/Sub topic. Save the returned `historyId` and `expiration` in a new service-only table `gmail_watches(user_id, connection_id, topic, expires_at, last_history_id)`. Renew the watch daily from the existing scheduled workflow (`.github/workflows/background-jobs.yml`), well before its 7-day expiry.
2. **Receive.** Pub/Sub pushes to `POST /internal/gmail/push`. The endpoint verifies the OIDC JWT that Pub/Sub signs (issuer `https://accounts.google.com`, audience = this endpoint's URL, `email` = the push service account), and rejects anything else with 401. The body is base64 JSON `{emailAddress, historyId}`.
3. **Map to a user.** Look up the connection by verified mailbox address, using a new `connections.google_email` column written at connect time. Unknown address: return 204 and do nothing, so Pub/Sub stops retrying without revealing anything.
4. **Record, don't process.** Insert `gmail_push_events(user_id, history_id, received_at)` idempotently, keyed by `(user_id, history_id)`, and return 204 within Pub/Sub's deadline. Duplicate deliveries are no-ops.
5. **Process.** Two options:
   - **A, no session-less work (recommended first).** On the user's next visit, Home sees a pending push event and starts the normal Gmail job with the user's own session. Latency becomes "next visit", but there is no change to the security model.
   - **B, true background.** A system job holds a scoped service grant that can only (a) read the encrypted Google token for that one `user_id`, and (b) call a fixed set of `security definer` RPCs that take an explicit `p_owner` and re-check `connection.user_id = p_owner`. Every use is written to an audit table. This needs its own threat model: a leaked worker secret must not allow reads of arbitrary users.
6. **Gaps.** If `history.list` returns 404 (history expired) or the stored id is older than the push, fall back to the existing full label re-scan (`_initial_page`). The cursor logic in `gmail_sync.py` already does this for manual sync.

## What the user must set up
- A Google Cloud Pub/Sub topic, with `gmail-api-push@system.gserviceaccount.com` granted Publisher on it.
- A push subscription to `https://focusos-api.vercel.app/internal/gmail/push`, with OIDC authentication using a dedicated service account.
- The topic name and the push service-account email, set as API environment variables.

## Tests to write with the implementation
JWT valid, expired, wrong audience and wrong issuer; an unknown mailbox; duplicate `historyId`; an out-of-order `historyId`; history 404 leading to a full re-scan; watch renewal before expiry; and that a push never processes another user's mailbox.
