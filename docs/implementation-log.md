# FocusOS Implementation Log

Last updated: 2026-09-26

This log records what was implemented and why, one increment at a time. The detailed product scope, acceptance criteria, architecture tradeoffs, and future increments remain in [plan.md](../plan.md).

## Current state

The chosen application shape is a Next.js web UI with a Python/FastAPI API (D1, Option B). Supabase Auth with Google sign-in is the selected application identity path (D2, Option A). Supabase client access with versioned SQL migrations is selected for persistence (D3, Option A). Code is in place through Increment 1.8. Google sign-in/sign-out, database identity, and profile save/read were verified against the linked Supabase project. The profile isolation check used a synthetic second identity in a rolled-back database transaction. Increments 1.1–1.8 are verified; Phase 1 is complete. The hosted web and API run on two Vercel Hobby projects. Phase 2 began after D4 was selected. Increments 2.1 and 2.2 are complete. D13 Option A (incremental consent and owned primary Calendar) is selected. Increment 2.3 code is implemented with live consent setup pending; 2.4 implementation, production build, and SQL grants are verified; live OAuth verification is pending. Increment 2.5 code and mocked tests are implemented; reading a live synthetic email remains pending. Increment 2.6 code, mocked verification, and database RPC grants are implemented; live Calendar read and consent verification remain pending.

## Step 0 — Product and architecture plan

**What was done:** Created the root implementation blueprint in `plan.md`. It defines the product goal, a Gmail-to-reviewed-task-to-approved-Calendar-event demo, security invariants, architecture decisions, costs, and small implementation increments.

**Why:** The project involves personal data and external calendar writes. A staged plan puts identity, ownership, evidence, and approval boundaries in place before those features are built. Decision gates keep later choices from being silently assumed.

**Result:** The plan is the scope reference. It does not mean that later capabilities described there have already been built.

## Decision D1 — Next.js UI + Python API

**Choice:** Option B, selected by the user. Hosting is still undecided.

**Why:** The web app stays in Next.js while the API and future AI/extraction work use Python. This keeps a clear UI/API boundary and supports Python-native AI work. The tradeoff is maintaining two runtimes and their API contract.

## Increment 1.1 — Minimal application foundation

**What was built:** A Next.js web app in `web/`, a FastAPI app in `backend/` with `GET /health`, root scripts for running each app, and the initial README and ignore rules.

**Why:** This creates a runnable base in both selected runtimes and checks the UI/API split before domain features are added.

**Verification:** The Next.js production build succeeded. The web root returned HTTP 200, and the API health route returned `{"status":"ok"}`.

## Increment 1.2 — Environment boundary

**What was built:** `web/src/server/env.ts` exports `requireServerEnv`, which checks that a requested variable name is valid and that its value is present. The root `.env.example` documents expected local values, and private `.env*` files are ignored by Git.

**Why:** Configuration mistakes should fail clearly without printing secret values. Keeping server environment access behind one helper makes the boundary visible and reusable.

**Verification:** Next.js build and TypeScript checks passed. Missing-variable behavior was later covered by the focused test harness in Increment 1.3.

## Increment 1.3 — Focused web test harness

**What was built:** Vitest configuration, two tests for the environment helper, and the `npm.cmd run test:web` command. Vitest is pinned to 4.1.11, and the README documents the check.

**Why:** The environment helper is server-side TypeScript that can be tested in Node without adding a browser or DOM test stack. A root command makes the check easy to repeat.

**Verification:** The web test command passed with 1 test file and 2 tests. The Next.js production build also passed. Dependency installation reported zero vulnerabilities after moving to the patched Vitest version.

## Decision D2 — Supabase Auth with Google sign-in

**Choice:** Option A, selected by the user: Supabase Auth manages the application session and Google is the sign-in provider. D3 is now selected separately below; D4 and later choices remain open.

**Why:** Supabase Auth gives the app a verified identity that maps naturally to `auth.users` and later row-level security. One Google sign-in flow is a small first authentication slice. Application identity and Gmail/Calendar authorization remain separate concerns: this increment does not request Gmail or Calendar scopes or store Google service tokens.

## Increment 1.4 — Google login and server-verified session

**What was built:**

- The home page now shows a Google sign-in button or the verified user's email and a sign-out button.
- A server action starts Google OAuth using the PKCE flow; the callback exchanges the code and returns to the app. Sign-out ends the local session.
- The server Supabase client reads and writes session cookies. The cookie configuration is `HttpOnly`, `SameSite=Lax`, secure in production, and uses Supabase SSR's `tokens-only` encoding.
- `getServerUser` calls Supabase `getUser` to verify the session, then returns only the user's ID and email. Invalid sessions and verification failures return no identity.
- The Next.js 16 `proxy.ts` calls `getClaims` so expired sessions can be refreshed.
- `.env.example` and the README explain the required Supabase URL, publishable key, app origin, and provider redirect setup.

**Why:** The server must verify identity before it is used for protected work. PKCE keeps the OAuth code exchange on the server. The helper returns a small DTO instead of session or token data. The service scopes are deferred until their planned consent and credential-protection increments.

**Verification:** `npm.cmd run test:web` passed with 2 test files and 5 tests, including verified identity projection, invalid sessions, and fail-closed behavior on verification errors. `npm.cmd run build:web` passed, including TypeScript and production compilation. `git diff --check` passed.

**Live verification (2026-09-26):** The user completed Google sign-in through the real Supabase project; the application callback returned to the signed-in home page. The initial Google `org_internal` rejection was resolved by changing the Google OAuth audience to External. The user then signed out. Server logs showed the authenticated database-check route succeeding before sign-out and returning 401 after sign-out, confirming session removal. The existing focused tests cover invalid identity and rejected redirect handling. No Gmail or Calendar grants were requested.

**Current boundary:** FastAPI still exposes only its initial health route; protected API identity propagation is later work. Gmail and Calendar scopes, Google token storage, and database access are also not implemented here.

## Decision D3 — Supabase client and versioned SQL migrations

**Choice:** Option A, selected by the user. SQL files are the single migration history, and ordinary API queries use the Supabase client with a verified user's access token. No ORM or service-role key is introduced for ordinary requests.

**Why:** This fits Supabase Auth and later row-level security while avoiding a pooled Postgres connection in the Python API. Narrow SQL functions can provide atomic operations when later increments need them. Restricting function execution and keeping requests user-scoped make the identity boundary visible.

## Increment 1.5 — Database access boundary (2026-09-25)

**Purpose:** Establish the database client and migration workflow, then probe whether Supabase Auth and PostgREST receive the same caller identity before adding domain tables.

**Files changed:** `backend/pyproject.toml`, `backend/src/focusos_api/database.py`, `backend/src/focusos_api/main.py`, `backend/tests/test_database.py`, root `package.json` and `package-lock.json`, `supabase/config.toml`, `supabase/migrations/20260925103118_verify_session_context.sql`, `web/src/app/api/db-check/route.ts`, `web/next.config.js`, `.env.example`, `README.md`, and `plan.md`. The editable Python install also refreshed tracked package metadata in `backend/src/focusos_api.egg-info/`.

**What was built and why:** The project-local Supabase CLI creates ordered SQL migrations. The first migration adds only `focusos_session_uid()`, a read-only `security invoker` function that returns `auth.uid()` with a fixed empty search path; only the `authenticated` role is granted execution. The FastAPI `GET /health/database` route rejects missing credentials, verifies a supplied access token through Supabase Auth, sends the same token to PostgREST, and compares the database user ID with the verified user ID. A fresh client and HTTP transport are used per request, and only a publishable key is accepted. Next.js `GET /api/db-check` checks the server session and forwards its token to FastAPI from the server, returning a small success/error response without disclosing the token. `web/next.config.js` fixes the web Turbopack root after adding a root CLI lockfile. Environment and run instructions now cover both processes and migration application.

**Verification:** `npm.cmd run test:api` passed 8 tests covering JWT propagation, identity mismatch, missing/invalid sessions, secret-key rejection, generic database failure handling, and minimal success output. These tests mock Supabase responses. `npm.cmd run build:web` passed TypeScript and the production build, including `/api/db-check`. The Supabase CLI initialized the local config and generated the migration file. No remote migration or live database query was run.

**Live verification (2026-09-26):** The CLI listed local and remote migration `20260925103118` as matched, and `db push --linked --dry-run` reported no pending migration. Supabase reported the Google provider enabled. A direct anonymous request to the read-only RPC returned HTTP 401. Local `GET /health/database` without a bearer token returned 401. With the user signed in through Google, Next.js `GET /api/db-check` returned 200 and FastAPI `GET /health/database` returned 200; after sign-out, `/api/db-check` returned 401. The browser received only the status/error JSON, not a token or identity.

**Known limitations:** This read-only probe confirms authenticated identity propagation and denies anonymous access, but no domain table exists yet. Table row isolation will be checked with the profile table and two users in 1.6.

**Next gated increment:** 1.6, owned profile and scheduling preferences.


## Increment 1.6 — Owned profile and scheduling preferences (2026-09-26)

**Purpose:** Store the user's timezone and working hours as the first user-owned domain data, and prove that another identity cannot access it.

**Files changed:** `supabase/migrations/20260926112710_owned_profiles.sql`, `backend/src/focusos_api/{database,main,profiles}.py`, `backend/tests/test_profiles.py`, `backend/pyproject.toml`, `web/src/server/api/profile.ts`, `web/src/app/settings/page.tsx`, `web/src/app/settings/actions.ts`, `web/src/app/page.tsx`, `web/src/app/globals.css`, `README.md`, `.gitignore`, and `plan.md`. Python editable-install metadata was refreshed.

**What was built and why:** The migration creates `profiles`, keyed to `auth.users`, with database checks for IANA timezone names and a compact working-hours JSON shape. Row-level policies restrict SELECT, INSERT, and UPDATE to the caller's own row; column grants keep `is_allowlisted` and timestamps outside user writes. An authenticated, security-invoker RPC atomically inserts or updates the caller's preferences. FastAPI verifies the access token and uses a fresh user-scoped Supabase client per request, validates inputs with Pydantic, and exposes GET/PUT `/profile`. The signed-in Next.js settings page uses a server-side bridge to FastAPI, so the form never handles tokens. Defaults are suggestions until the user saves them.

**Verification:** `npm.cmd run test:api` passed 14 tests, including invalid timezone/range/duplicate days, anonymous access, and rejection of a client-supplied allowlist flag. `npm.cmd run build:web` and TypeScript checking passed. The migration was applied to the linked Supabase project. Direct live checks found anonymous profile table/RPC access denied, authenticated preference grants present, and no authenticated update grant for the allowlist flag. Live FastAPI logs showed profile GET 200, PUT 200, and subsequent GET 200; the Next.js settings redirect returned with `saved=1`. A rolled-back database transaction impersonated the saved profile's owner and then a second synthetic authenticated identity: the owner could select/update one row; the second identity selected/updated zero rows. This validates policy behavior without creating a second Google account or persisting the test update.

**Limitations:** The user-facing reload result was not separately reported in chat at the time of this entry; server requests show the saved profile was read again. The second identity was synthetic, not a second live Google login. Calendar selection, scheduling, tasks, and Google service grants remain later work.

**Next gated increment:** 1.7, the protected `/api/me` contract and signed-in shell.

## Increment 1.7 — Protected identity API and signed-in shell (2026-09-26)

**Purpose:** Provide a small authenticated UI-to-API contract before adding feature routes, and show saved scheduling context in the signed-in home page.

**Files changed:** `web/src/server/api/me.ts`, `web/src/app/api/me/route.ts`, `web/src/app/page.tsx`, `web/tests/me.test.ts`, `README.md`, `plan.md`, and this log.

**What was built and why:** The server composes a freshly verified Supabase user with the owned profile returned by FastAPI. It explicitly projects only user ID/email and timezone/working hours, rejects a mismatched profile owner, and returns a narrow error state if the profile backend is unavailable. `GET /api/me` returns this nonsecret DTO with `Cache-Control: no-store`, or a safe 401/503 error envelope. The home page consumes the same server contract and displays the saved timezone and working days; it keeps sign-out available if the profile backend fails.

**Verification:** `npm.cmd run test:web` passed 8 tests across 3 files, including anonymous denial, safe projection when an upstream object contains canary secret fields, and owner mismatch. `npm.cmd run build:web` passed and includes the dynamic `/api/me` route. A local anonymous `GET /api/me` returned HTTP 401, `Cache-Control: no-store`, and the safe unauthorized error envelope. The local development server logged a signed-in `GET /api/me` 200 followed by FastAPI `GET /profile` 200; a separate anonymous request returned 401. The user confirmed that the browser response contained `user` and `profile` without a token.

**Limitations:** The authenticated route succeeded locally; hosted behavior remains for 1.8. There is no task dashboard or integration data.

**Next gated increment:** 1.8, deploy the small authenticated slice after the hosting branch and account are confirmed.


## Increment 1.8 — Early hosted deployment probe (2026-09-26)

**Purpose:** Expose serverless/runtime and OAuth configuration problems while the application is still a small authenticated slice.

**Files changed:** `backend/src/index.py`, `backend/.python-version`, `backend/vercel.json`, `web/vercel.json`, `docs/deployment.md`, `README.md`, `.gitignore`, `plan.md`, and this log.

**What was built and why:** Two Vercel projects were created under the user's Hobby team: `focusos-api` for FastAPI and `focusos-web` for Next.js. Each has its own Production environment values and stable domain. The Python entrypoint exports the existing FastAPI app, Python is pinned to 3.12, and both `vercel.json` files select the correct framework. The initial API deployment returned 404 because Vercel chose the generic Other preset; the web initially built as Other and looked for a nonexistent `public` output directory. Explicit framework presets fixed both. The actual web alias was `focusos-web-five.vercel.app`, so `FOCUSOS_APP_URL` was corrected and the web project redeployed. The Supabase OAuth redirect allowlist was extended to this domain.

**Hosted URLs:** Web: https://focusos-web-five.vercel.app ; API: https://focusos-api.vercel.app . They are CLI deployments from `web/` and `backend/`. Git-triggered deployment is not configured yet; `docs/deployment.md` gives the commands and explains how to connect the repository later.

**Verification:** The Vercel team list reports Hobby. API `GET /health` returned 200 with `{"status":"ok"}`; anonymous `GET /profile` and `GET /health/database` returned 401. The hosted web root returned 200, anonymous `GET /api/me` returned 401 with `Cache-Control: no-store`, and anonymous `/settings` redirected to the root. After the redirect allowlist update, the user completed hosted Google login and confirmed `/api/me` returned 200 with `user` and `profile`. The user confirmed that hosted settings persisted after reload, and `/api/me` returned 401 after sign-out. All required hosted smoke checks passed.

**Limitations:** Python runtime is beta, the two project deployments are currently issued through the CLI, and Git pushes do not auto-update them. No background execution or public Gmail/Calendar grant is claimed.

**Next gated increment:** 2.1 after the Phase 2 credential-storage decision gate.

## Decision D4 - FastAPI application encryption

**Choice:** Option A, selected by the user: FastAPI will encrypt OAuth token values with authenticated encryption before persistence. The key belongs in private server configuration, outside PostgreSQL and browser-visible variables.

**Why:** This fits the Python API that owns Google integration work and keeps plaintext tokens out of database storage. The tradeoff is that the application must protect, back up, version, and rotate its encryption key.

## Increment 2.1 - Google connection metadata and private credential storage (2026-09-26)

**Purpose:** Create a safe database destination and owner-scoped status record before adding any OAuth exchange or refresh behavior.

**Files changed:** supabase/migrations/20260926150000_google_connection_storage.sql, backend/src/focusos_api/connections.py, backend/src/focusos_api/main.py, backend/tests/test_connections.py, plan.md, and this log.

**What was built and why:** The migration adds one Google connection per user, owner-only metadata reads under RLS, and a private.oauth_credentials table for encrypted access/refresh token bytes, expiry, key version, token version, and refresh lease metadata. Browser roles receive no schema or table access to the credential store. The authenticated API can only read the explicitly granted safe metadata columns; it cannot read provider_subject or write connection records. A protected GET /connections/google route and repository method use the verified caller's JWT, owner predicate, and a narrow response model that excludes provider identity and credentials.

**Verification:** The full backend test suite passed (18 tests). The migration dry-run listed only this migration, and it was applied to the linked Supabase project. Live grant checks confirmed anon and authenticated cannot access the private schema or credential table; authenticated users can read approved metadata columns but not provider_subject and cannot insert connections. A rolled-back live RLS probe returned one visible row for its owner and zero for a second authenticated identity. git diff --check passed.

**Stop point:** No OAuth code exchange occurred, no Google tokens were requested or stored, and the encryption key/helper is not configured yet. These are 2.2 and later work.

**Next gated increment:** 2.2, implement authenticated encryption and the expiry-aware refresh helper. No Google consent request yet.

## Increment 2.2 - Token protection and refresh helper (2026-09-26)

**Purpose:** Encrypt OAuth credentials with a deployment-managed key and refresh expired access tokens without losing the refresh grant or allowing competing requests to overwrite one another.

**Files changed:** backend/src/focusos_api/token_crypto.py, backend/src/focusos_api/google_tokens.py, backend/src/focusos_api/google_token_store.py, backend/src/focusos_api/database.py, backend/tests/test_token_crypto.py, backend/tests/test_google_tokens.py, backend/tests/test_google_token_store.py, backend/tests/test_database.py, backend/pyproject.toml and editable package metadata, supabase/migrations/20260926160000_google_token_refresh_functions.sql, README.md, plan.md, and this log.

**What was built and why:** AES-GCM uses a fresh 96-bit nonce for each token and authenticates the connection ID, token type, and key version as associated data. A server-only JSON keyring supports decrypting older key versions while encrypting with the active one. The refresh helper reuses unexpired access tokens, claims a bounded database lease before refreshing, performs one server-side Google token request, preserves an existing refresh token when Google omits a replacement, and saves via a versioned compare-and-swap. An invalid_grant marks the connection reconnect_required. Private token reads and refresh mutations go through security-definer RPCs executable only by service_role; user and anonymous roles cannot execute them. The service-role client requires a distinct server secret and is kept separate from normal user-scoped database access.

**Verification:** All 33 backend tests passed, including random-nonce encryption, AAD/tamper rejection, key rotation, expired-token refresh, preservation of the refresh token, invalid_grant handling, and two competing refresh calls producing only one provider request. The SQL migration was first compiled in a rolled-back linked transaction, then applied to Supabase. Live grant checks confirmed only service_role can execute token RPCs. A second rolled-back SQL probe verified lease exclusivity, successful versioned save, stale-save rejection, and reconnect_required transition. No real Google token or provider request was used.

**Stop point:** Token exchange is not implemented yet. D13 was selected as Option A before increment 2.3. The API-host service key, encryption keyring, and Google client secret must be set privately before live callback verification in 2.4.

**Next gated increment:** 2.3, implement the selected Google consent start flow.

## How this log will be maintained

After each future increment, append a dated section with the increment number, purpose, files changed, what was added and why, commands/tests and their results, manual verification, known limitations, and the next gated increment. Keep incomplete live checks explicitly marked as pending. Do not mark plan checklist items complete unless their stated acceptance checks actually passed.

## Increment 2.3 - Session-bound Google consent start

**What changed:** Added a Google consent settings page and authenticated OAuth start/callback routes. The initial grant requests Gmail read-only and read-only events from calendars the user owns, alongside OpenID identity scopes. Calendar write scope is reserved for the later upgrade. The callback uses the fixed app callback URL, PKCE S256, offline access, incremental grants, and a short-lived HttpOnly, callback-path cookie. Its AES-GCM-protected payload binds the random OAuth state and PKCE verifier to the signed-in FocusOS user. The callback validates that binding, strips the provider code from the redirect, clears the one-use cookie, and does not yet exchange or store tokens.

**Why:** Keep this increment focused on validating consent, state, redirect, and scope boundaries before adding a live token exchange. Binding and encrypting state prevents cross-user callback reuse and disclosure of the PKCE verifier through the browser cookie. Incremental consent avoids asking for Calendar write access before scheduling exists; using the known primary Calendar avoids broad calendar-list permission.

**Configuration:** Added `FOCUSOS_GOOGLE_CLIENT_ID` and a distinct 32-byte Base64 `FOCUSOS_GOOGLE_STATE_SECRET` to the web server environment. README documents exact local and hosted callback URLs, API enablement, test-user setup, and key generation. The Google client secret remains only in the FastAPI environment for the token exchange increment.

**Verification:** Web tests pass (14 tests across 4 files). Production Next.js build passes and includes the connection page and both OAuth routes. `git diff --check` passes. Live consent remains pending: register the two callback URIs in Google Cloud, set the two web environment values, then verify the consent return from a signed-in test account. No authorization code or Google token is exchanged or persisted in this increment.

**Next:** Increment 2.4, exchange the authorization code in FastAPI, validate Google identity/scopes, encrypt and persist tokens through the private credential RPC, and verify callback completion end to end.

## Increment 2.4 - Secure callback and connection status

**What changed:** The Next.js callback now validates the one-use encrypted state cookie, retrieves the signed-in user's verified Supabase session token, and posts the authorization code plus PKCE verifier directly to FastAPI. FastAPI authenticates the caller, checks an exact callback allowlist, exchanges the code with Google's token endpoint, verifies the granted read scopes and Google userinfo identity, encrypts both tokens with the configured AES-GCM keyring, and stores them through narrowly granted service-only RPCs. The settings page reads only owner-scoped metadata and shows the Google email and granted capabilities. Browser responses contain no Google token or code.

**Why:** The API owns Google client-secret access, encryption keys, and token persistence. Supabase identity determines the FocusOS owner; the verified Google `sub` identifies the connected provider account. Database functions prepare a stable connection UUID before encryption because the encryption AAD binds ciphertext to that UUID, then store metadata and ciphertext atomically. New unfinished connections remain `reconnect_required` until ciphertext is stored successfully.

**Configuration:** FastAPI requires `FOCUSOS_GOOGLE_CLIENT_ID`, `FOCUSOS_GOOGLE_CLIENT_SECRET`, `FOCUSOS_GOOGLE_REDIRECT_URIS`, the Supabase service-role key, and the versioned token-encryption keyring. The web server requires its existing client ID, state key, API URL, and session settings. README and `.env.example` document the split; no secret belongs in browser variables.

**Verification:** Backend tests cover code exchange, PKCE forwarding, strict callback allowlisting, read-scope validation, identity verification, ciphertext round-trip, anonymous denial, and token-free response (39 backend tests pass). Web tests pass (14 tests). Production build passed. The migration was applied and rollback-probed; a live grant query confirmed only service_role can execute the RPCs. Live Google consent remains pending private provider configuration and callback registration. No live token was used in tests.

**Next:** Increment 2.5, read one explicitly selected synthetic Gmail message through the backend without persisting message content.

## Increment 2.5 - Read one selected Gmail message

**What changed:** Added an authenticated FastAPI probe that accepts one message ID, checks the user's connection and Gmail read grant, obtains a fresh Google access token through the encrypted refresh store, and calls Gmail `users.messages.get` with `format=full`. It decodes a text/plain body only in memory and returns the selected ID, date, label count, and body byte count. The settings page provides a message-ID field and the Next.js proxy keeps the Supabase access token server-side. No message content is returned or persisted.

**Why:** The first Gmail acceptance test needs evidence that the granted scope can read one chosen synthetic message without turning the probe into inbox sync or retaining personal email. The read endpoint is scoped to an explicit ID, and the response omits snippet, headers, and body.

**Verification:** Backend tests cover scope denial, invalid IDs, token access, provider authorization failure, byte-count extraction, anonymous denial, and content-free response (45 tests pass). Web tests pass (16 tests), production build includes the dynamic Gmail route, and Python compilation passes. A real Gmail request remains pending Google connection and a synthetic message ID; obtain the ID with Gmail `users.messages.list` and enter it on Settings > Google connections. No real email or body was used in tests.

**Next:** Increment 2.6, read a bounded Calendar events page and add a separate incremental-consent route to verify the write-capable grant without creating or changing any event.

## Increment 2.6 - Calendar page probe and write-grant upgrade

**What changed:** Added a separate authenticated consent start route for the owned-calendar event-write scope. The OAuth state cookie encrypts and binds the flow type to the signed-in user, and the callback routes this flow to a dedicated FastAPI endpoint. FastAPI requires the combined read and write scopes, verifies the Google account subject matches the existing connection, and updates the stored grant through a service-only RPC. If Google omits a replacement refresh token, the API decrypts the existing token and re-encrypts it with the active key version before saving. Added a primary Calendar events probe for a fixed seven-day window and at most ten results; the UI receives only event count and whether another page exists. No event write endpoint or event mutation is invoked.

**Why:** Calendar read is needed to validate the chosen account and available events before scheduling. Write permission is requested only as a distinct user-initiated upgrade, consistent with D13 Option A. Keeping the write grant separate makes the consent boundary visible; the increment verifies permission without exercising a write. The database checks the same owner and provider subject so an account switch cannot overwrite the established connection during scope upgrade.

**Verification:** Backend tests pass (54 total), including wrong-account denial, partial-scope denial, refresh-token preservation/key rotation, bounded primary-calendar query, scope denial, and no event-detail response. Web tests pass (20 total), including separate consent scope, authenticated callback routing, and metadata-only proxy. Production build passes. The migration was applied; rollback probe verified matching-subject update, mismatched-subject no-op, and no persistent test data. Live Calendar read and Google consent upgrade remain pending private provider configuration. No event was created, changed, or deleted. FocusOS will not expose event deletion even though Google?s owned-events write scope allows it at the provider level.

**Next:** Phase 2 implementation is complete. Live acceptance remains: configure Google/FastAPI environment values, connect a test account, read one synthetic Gmail message, read a primary Calendar page, and grant the Calendar write scope through the upgrade screen.

## Increment 3.1 - Owned task storage

**What changed:** Added the owner-scoped tasks table, title/description/status/priority and estimate constraints, separate date-only and timestamp deadlines, due-timezone validation, version metadata, and indexes for open work ordered by either deadline kind. RLS exposes only a user's own task rows. Added a rollback-only SQL probe for owner and non-owner reads. Selected D7 Option A: projects, tasks, sources, and memories stay relational, with ordinary foreign keys and typed records.

**Why:** PostgreSQL constraints keep invalid deadline combinations out even if a caller bypasses API validation. Separate DATE and timestamptz fields preserve the distinction between a calendar date and a precise instant. Row Level Security provides database-enforced isolation in addition to the verified session boundary. The relational design is sufficient for the MVP's known relationships and keeps same-owner references enforceable.

**Verification:** Applied migration 20260926200000_owned_tasks.sql to the linked Supabase project. Ran supabase db query --linked --file supabase/tests/20260926200000_tasks_rls.sql; the owner saw the temporary task, a different Auth subject saw no row, and the transaction rolled back. No task data remains from the probe.

**Next:** Increment 3.2 adds strict runtime payload validation and boundary tests.

## Increment 3.2 - Runtime task validation

**What changed:** Added a strict Pydantic create schema for task title, description, priority, date-only deadlines, zoned instants, and estimates. Unknown fields are rejected, text is normalized, estimates are bounded to 1-1440 minutes, and a datetime's supplied UTC offset must agree with its IANA timezone. Date-only strings must match YYYY-MM-DD exactly.

**Why:** API validation provides clear client errors before database access, while the database constraints from 3.1 remain the final guard. Keeping due_date distinct from due_at prevents an all-day deadline from becoming an invented midnight instant. Validating zone/offset consistency prevents a timestamp from silently describing a different local time than the user selected.

**Verification:** The complete backend unittest suite passes: 63 tests, including 9 task-payload tests for required field shapes, impossible/ambiguous dates, time-zone and offset mismatches, enum/extra-field rejection, and input boundaries.

**Next:** Increment 3.3 adds authenticated, owner-scoped task create/list endpoints and replay-safe creation.

## Increment 3.3 - Authenticated task create and list API

**What changed:** Added GET /tasks with an optional status filter and a bounded 100-row page, plus POST /tasks requiring a UUID Idempotency-Key. Both use the verified Supabase session and owner-scoped database access. Creation goes through a narrowly granted RPC that derives ownership from auth.uid(), stores a SHA-256 fingerprint of normalized input, and atomically returns the existing row for a retry. Reusing a key with different input returns HTTP 409. Internal hashes and owner IDs stay out of API responses.

**Why:** A request can reach the server and still lose its response; the stable key prevents a client retry from creating duplicate tasks. Comparing the stored fingerprint prevents one key from silently representing two different user actions. The authenticated endpoint and database policy provide independent checks for access and ownership.

**Verification:** Applied the replay RPC and its strict hash-pair constraint to linked Supabase. Ran a rollback-only SQL probe through the deployed RPC: first request created one row, an identical replay returned that same ID, and different input returned the original row/hash for API conflict handling. The transaction rolled back. The complete backend suite passes (71 tests), including anonymous denial, owner filters, bounded results, replay conflicts, validation, and token-free response checks.

**Next:** Increment 3.4 adds the authenticated task form/list in the web app and verifies persisted reload behavior.

## Increment 3.4 - Task form and list

**What changed:** Added an authenticated task board to the signed-in home page, with title, details, priority, date-only deadline, estimate, open-task list, and a reload control. A Next.js route proxies GET/POST requests to FastAPI using the verified Supabase session token on the server. The proxy restricts filters, bounds request size, disables redirects, maps safe errors, and marks responses no-store. Retries reuse a key only when the exact payload matches.

**Why:** The first user-facing slice can now create and read the durable tasks introduced in 3.1-3.3. The session token never enters client JavaScript or API responses. The initial form supports date-only deadlines, avoiding an incorrect conversion from the browser's timezone into a saved instant; timed deadlines can be added when the UI has an explicit timezone flow.

**Verification:** Web tests pass (26 tests across 5 files), including anonymous denial, server-only token forwarding, input filtering, request-key handling, safe conflict mapping, and token-free responses. The production Next.js build passes and includes /api/tasks. The UI reloads the open-task list after saving and exposes a manual reload control.

**Next:** Increment 3.5 adds relational projects and same-owner project association to tasks.

## Increment 3.5 - Projects and owned task association

**What changed:** Added owner-scoped relational projects with case-insensitive, per-user unique names; authenticated project list/create API; project selection and creation in the task board; and an optional task project reference. The database uses a composite user_id/project_id foreign key so a task cannot point to another user's project. The create RPC derives the owner from auth.uid() and returns a generic unavailable-project result that the API maps to 404.

**Why:** D7 Option A keeps known relationships explicit and enforceable in SQL without a generic edge graph. The composite foreign key is a final database boundary, while the RPC check gives the caller a clean response without confirming whether a foreign project ID exists. Case-insensitive uniqueness prevents duplicate copies of the same project name for one owner.

**Verification:** Applied migration 20260926220000_projects_task_association.sql. The rollback-only Supabase integration probe verified case/whitespace-insensitive project dedupe, task association to an owned project, zero project visibility and rejected association for a different Auth subject, then rolled back all probe data. The Phase 2/3 backend suite passes (80 tests); web tests pass (29 tests across 6 files); production build and TypeScript checks pass.

**Next:** Increment 3.6 adds version-checked task edits/completion and a deterministic Today task list.

## Increment 3.6 - Versioned edits and Today task ordering

**What changed:** Added strict task PATCH validation with expected_version, an atomic compare-and-swap database function, and a 409 response containing the latest owned task when another edit won first. Title edits and completion controls use this version check. Added a timezone-aware Today endpoint: it includes open tasks due today or earlier plus undated open tasks, excludes future-dated work, and orders by deadline date, priority, then stable task ID. A profile supplies the IANA timezone; UTC is the explicit fallback when no profile exists.

**Why:** Compare-and-swap prevents stale pages or retries from silently overwriting newer task changes. The Today query uses local calendar-date boundaries, including DST transitions, so a day is not treated as a fixed 24-hour duration. Sorting happens deterministically in the API instead of depending on browser order.

**Verification:** Applied migration 20260926230000_task_versions_today.sql. The rollback-only Supabase probe verified a version-1 update to version 2, rejection of a second version-1 edit with the latest row returned, and no task visibility/update for another Auth subject; all probe data rolled back. Backend tests pass (92 total), web tests pass (34 across 7 files), and the production Next.js build/TypeScript check passes. Live Google provider acceptance from Phase 2 remains separate.

**Deployment:** On 2026-09-27, deployed API commit 2b116cb to https://focusos-api.vercel.app and web commit 2b116cb to https://focusos-web-five.vercel.app. Both Vercel production deployments reached READY. Smoke checks returned API /health 200, anonymous /api/me 401, anonymous /api/tasks/today 401, anonymous /api/projects 401, and anonymous task POST 401 without creating data. The authenticated browser task create/reload/edit/complete lifecycle still needs a signed-in browser session.

## Phase 4: ekstraksi terstruktur

Keputusan D5: opsi A. FocusOS menyimpan teks sumber manual yang dinormalisasi maksimal 20 KB selama 30 hari. Teks ini memungkinkan pemeriksaan kutipan bukti dan ekstraksi ulang tanpa bergantung pada pesan Gmail yang mungkin berubah atau hilang. Pembersihan maksimal 100 sumber kadaluarsa dijalankan pada request sumber milik pengguna; metadata dan hash tetap tersedia untuk jejak asal. Input manual tidak mengambil URL atau gambar dari internet.

Keputusan D12 untuk generasi: opsi A, OpenAI Responses API dengan Structured Outputs dan validasi Pydantic tambahan. Model dan versi prompt dicatat per eksekusi; kemampuan embedding diputuskan dan diuji tersendiri sebelum 7.5. Akun OpenAI API dengan kuota serta API key backend diperlukan untuk panggilan nyata; akun ChatGPT saja tidak menyediakan key API. Key tidak disimpan di Git atau dikirim ke browser.

### Increment 4.1 - Sumber manual dan provenance

**Yang dibuat:** Tabel `source_items` dengan RLS per pemilik, hash SHA-256 teks normal, waktu penerimaan, identitas sumber, batas 20 KB, serta waktu kedaluwarsa isi 30 hari. Endpoint POST /sources/manual memakai Idempotency-Key dan RPC atomik sehingga pengulangan menghasilkan sumber yang sama; key yang dipakai untuk input berbeda menghasilkan konflik. GET /sources dan GET /sources/{id} hanya mengembalikan sumber milik sesi terkait. Fungsi pembersihan isi dibatasi 100 baris per request.

**Mengapa:** Calon tugas dari AI harus dapat ditelusuri ke isi tertentu; hash dan replay key menghindari duplikasi serta memisahkan ulang-kirim request dari sumber baru. RLS dan RPC pemilik menjadi batas keamanan di database, sedangkan batas ukuran/retensi mengurangi penyimpanan data pribadi.

**Verifikasi:** Migration 20260927010000_manual_sources.sql berhasil diterapkan ke Supabase. Suite API dan tes sumber manual lulus. Uji browser autentikasi tetap perlu dilakukan oleh pengguna.

### Increment 4.2 - Kontrak kandidat dan fixture tanggal

**Yang dibuat:** Skema Pydantic ketat untuk tugas, event, fakta, permintaan, bukti, dan envelope versi 1. Referensi kandidat bersifat lokal; UUID milik database tidak dapat ditentukan model. Validasi deterministik memeriksa kutipan terhadap teks sumber, referensi sumber, waktu acuan, tanggal kalender, zona IANA, dan perhitungan tenggat relatif terhadap event. Jumlah total kandidat dibatasi sepuluh.

**Mengapa:** Format JSON yang sah belum membuktikan kebenaran isi. Tenggat `unresolved` tetap eksplisit, sehingga model tidak boleh mengarang jam batas atau membuat tanggal ambigu menjadi pasti.

**Verifikasi:** Fixture pengembangan meliputi Kamis sebelum presentasi Jumat, bukti palsu, tanggal ambigu, tanggal kalender tidak valid, waktu eksplisit dengan zona, serta field tambahan/bukti kosong. Semua tes kontrak lulus.

### Increment 4.3 - Panggilan ekstraksi terstruktur

**Yang dibuat:** Adapter OpenAI Responses API untuk model `gpt-4.1-mini`, dengan JSON Schema ketat, `store=false`, batas output, timeout 25 detik, dan maksimal satu perbaikan bila JSON atau bukti tidak valid. Input sumber diberi label sebagai data tak tepercaya. Output diperiksa ulang oleh kontrak Pydantic dan validasi kutipan/tanggal; kegagalan mempunyai jenis eksplisit tanpa menghasilkan tugas.

**Mengapa:** Struktur dari provider mengurangi JSON rusak, tetapi pemeriksaan lokal tetap perlu karena struktur tidak membuktikan fakta, kepemilikan, atau tanggal relatif. Key disimpan hanya di FastAPI melalui `FOCUSOS_OPENAI_API_KEY`. Key tidak boleh berada di `web/.env.local`, browser, Git, atau log.

**Setup dan batas verifikasi:** Buat API key di OpenAI Platform dan pastikan proyek punya kuota penggunaan. Isi `FOCUSOS_OPENAI_API_KEY` dalam environment backend lokal dan Vercel project API untuk production; deploy ulang API setelah menambahkannya. Saat increment ini dikerjakan, key belum tersedia di lingkungan kerja, sehingga uji provider nyata dengan sumber sintetis masih tertunda. Tes mock menguji keberhasilan, usage, bukti palsu, refusal, timeout, dan konfigurasi kosong.

### Increment 4.4 - Catatan eksekusi agent

**Yang dibuat:** Tabel `agent_runs` dengan pemilik dan sumber yang sama, status, provider/model/versi prompt/skema, waktu mulai-selesai, latensi nyata, token bila provider melaporkannya, dan kode kesalahan aman. Wrapper mencatat awal lalu akhir panggilan model, termasuk kegagalan.

**Mengapa:** Kita perlu melihat kegagalan dan biaya penggunaan tanpa menyimpan prompt mentah, isi sumber, access token, atau API key di log. Relasi sumber-pemilik dan RLS mencegah pembacaan run pengguna lain.

**Verifikasi:** Migration 20260927020000_agent_runs.sql diterapkan. Tes kegagalan memastikan status serta kode timeout dicatat tanpa teks sumber atau token.

### Increment 4.5 - Hasil review yang tahan retry

**Yang dibuat:** `extraction_results` unik untuk kombinasi sumber, hash isi, versi skema/prompt/model. RPC klaim memakai lock per pengguna, lease 90 detik, dan batas lima run dalam sepuluh menit; hasil siap dikembalikan ulang tanpa panggilan model baru. Endpoint POST /sources/{id}/extract melakukan klaim, run, lalu menyimpan payload tervalidasi atau kode kegagalan aman; GET /sources/{id}/extraction membaca statusnya.

**Mengapa:** Request dapat terputus saat model bekerja. Status `processing` mencegah panggilan paralel yang sama, sementara lease memungkinkan pemulihan setelah fungsi server berhenti. Hasil kandidat baru bersifat review; belum menjadi tugas.

**Verifikasi:** Migration 20260927030000_extraction_results.sql diterapkan. Tes route menolak pengunjung anonim dan membuktikan hasil `ready` dipakai ulang tanpa provider call. Suite API lulus.

### Increment 4.6 - Konfirmasi kandidat menjadi tugas

**Yang dibuat:** Kolom provenance pada tugas untuk sumber, hasil ekstraksi, referensi kandidat, bukti, dan confidence. Endpoint POST /extractions/{id}/confirm menerima data tugas yang sudah dikoreksi pengguna, memvalidasi ulang ekstraksi terhadap sumber, lalu memakai RPC atomik untuk membuat satu tugas. Kunci unik kandidat dan hash review membuat retry identik aman dan perubahan detail pada retry menjadi konflik.

**Mengapa:** Kandidat AI tidak boleh langsung menjadi tugas. Pengguna menegaskan judul, prioritas, proyek, estimasi, dan tanggal; bukti tetap ditautkan ke sumber. Pemeriksaan hash sumber dan kepemilikan mencegah konfirmasi hasil yang usang atau milik pengguna lain.

**Verifikasi:** Migration 20260927040000_confirm_extraction.sql diterapkan. Tes API menolak sesi anonim, tanggal tidak valid, dan mengembalikan konflik yang aman. Tes browser autentikasi dan panggilan model nyata masih menunggu key/sesi pengguna.

### Increment 4.7 - UI review dan koreksi

**Yang dibuat:** Halaman `/activity` untuk menempel sumber manual, membaca sumber tersimpan, menjalankan ekstraksi, melihat kutipan bukti serta ketidakpastian, mengoreksi judul/prioritas/tanggal/estimasi/proyek, lalu mengonfirmasi atau mengabaikan kandidat. Keputusan ignore dapat dibatalkan dan disimpan di database. Proxy Next.js meneruskan JWT hanya dari sesi server, membatasi path dan ukuran request, serta menutupi detail error backend. Today menautkan tugas hasil review ke sumbernya.

**Mengapa:** Confidence model bukan persetujuan pengguna. Tampilan bukti membuat usulan dapat diperiksa; tanggal ambigu dibuka sebagai tanpa tenggat sampai pengguna mengoreksinya. Pemisahan source, ekstraksi, dan konfirmasi mencegah satu klik model langsung membuat tugas.

**Verifikasi:** Migration 20260927050000_extraction_ignore.sql diterapkan. 38 tes web dan 113 tes API lulus; production build Next.js lulus. Probe Supabase rollback-only berhasil melewati source -> claim -> run -> result -> confirm -> replay, membuktikan tugas open tanpa tenggat eligible di Today dan RLS menyembunyikan source/task dari subjek lain. Uji browser end-to-end dan satu panggilan model nyata tetap menunggu key OpenAI dan sesi pengguna.

**Deployment:** On 2026-09-27, API deployment dpl_EsfyXwA2qYj8yP4TVeEx4JnPYH2g and web deployment dpl_EKfqC3R6iPMJ2HFfJCh64zWrwgnR reached READY on their stable aliases. Smoke checks: API health 200, review page 200, anonymous source/read/confirm 401. Vercel API environment names currently contain Supabase URL/publishable key but no OpenAI key. The live model and authenticated browser journey remain outstanding; details are in `docs/deployment.md`.

## Phase 5: sinkronisasi Gmail terbatas

Keputusan D9: opsi A, sinkronisasi manual satu halaman per request. Tidak ada cron atau pekerjaan yang diam-diam terus berjalan ketika halaman ditutup. Email dipilih hanya jika memiliki label Gmail milik pengguna bernama `FocusOS`; pengguna membuat label itu sendiri karena aplikasi hanya meminta izin baca. Google OAuth harus mempunyai scope `gmail.readonly` dan backend harus memiliki rahasia OAuth serta kunci enkripsi token. Handoff ekstraksi model tetap membutuhkan API key.

### Increment 5.1 - Daftar ID dan metadata terpilih

**Yang dibuat:** Klien Gmail memeriksa grant, mengambil ID label `FocusOS`, lalu memanggil `messages.list` maksimal sepuluh ID dan `messages.get(format=metadata)` hanya untuk ID tersebut. API mengembalikan subject, sender, timestamp, thread/history ID, label, dan token halaman; isi pesan/snippet/token Google tidak keluar.

**Mengapa:** Label eksplisit membatasi pilihan sebelum teks pribadi diambil atau dikirim ke model. ID label, bukan pencarian seluruh inbox atau status unread, menjadi batas pemilihan yang konsisten.

**Verifikasi:** Tes provider membuktikan filter label, batas sepuluh, permintaan metadata saja, pagination, label hilang, serta penolakan anonim. Uji Gmail langsung menunggu koneksi/secret production.

### Increment 5.2 - Pengambilan isi pesan terpilih

**Yang dibuat:** Service mengambil maksimal tiga ID unik per request. Sebelum `format=full`, setiap ID diverifikasi ulang melalui metadata bahwa label `FocusOS` masih terpasang. Respons Gmail dibatasi 512 KB per pesan; pesan yang terhapus ditandai unavailable. Route diagnostik hanya mengembalikan ID/status, bukan MIME, body, atau token.

**Mengapa:** Daftar ID dari browser tidak boleh menjadi otorisasi untuk membaca pesan mana pun. Pemeriksaan label tepat sebelum fetch dan batas ukuran menutup celah antara listing dan pengambilan isi.

**Verifikasi:** Tes membuktikan pesan tanpa label tidak pernah diminta dalam format full, ID/path tidak valid ditolak sebelum Google, serta route anonim ditolak.

### Increment 5.3 - Normalisasi MIME murni

**Yang dibuat:** Parser tanpa network untuk base64url, charset, multipart bersarang, preferensi text/plain lalu HTML aman, timestamp/thread/history, penanda lampiran, pemotongan UTF-8 maksimum 20 KB, dan penghilangan blok kutipan balasan yang jelas. Script/style/iframe/SVG dan URL gambar tidak diambil; lampiran tidak diunduh.

**Mengapa:** Model harus menerima teks yang konsisten dan terikat pada sumber yang sama. Normalisasi sebagai fungsi murni mudah diuji dengan fixture tanpa membuka Gmail sungguhan. Pesan hanya berisi lampiran tidak dipaksa menjadi tugas.

**Verifikasi:** Fixture Unicode, HTML dengan script/gambar, nesting, teks panjang, kutipan balasan, lampiran-only, dan encoding invalid lulus.

### Increment 5.4 - Upsert sumber Gmail idempoten

**Yang dibuat:** `source_items` menampung sumber Gmail dengan connection ID, provider message ID, thread/history, sender, label pilihan, attachment flag, serta content_version. Kunci unik per koneksi dan message ID memastikan fetch berulang atau serentak memakai satu source ID. Hash isi berubah menaikkan versi; isi yang sama setelah pembersihan retensi dapat dipulihkan tanpa mengarang versi konten baru. Route ingest memakai pemeriksaan label dari 5.2 dan normalizer 5.3.

**Mengapa:** Identitas provider, bukan kesamaan teks, adalah dasar deduplikasi: dua pesan yang kebetulan sama harus tetap dua sumber. Hasil ekstraksi dipisah berdasarkan hash, sehingga konten berubah tidak diam-diam mengganti hasil review lama.

**Verifikasi:** Migration 20260927060000 dan perbaikan 20260927061000 diterapkan. Probe SQL rollback-only menegaskan replay ID sama, konten berubah menjadi versi 2, dua pesan berbeda tetap dua sumber, dan pengguna asing melihat nol baris. Tes repository/route lulus.

### Increment 5.5 - Handoff satu sumber Gmail ke review

**Yang dibuat:** RPC memilih satu sumber Gmail milik pengguna dengan teks aktif dan tanpa hasil ekstraksi siap/claim aktif untuk hash/versi sekarang. Endpoint process-one memanggil service ekstraksi Phase 4, sehingga run log, dedup, lease, bukti, dan UI review tetap satu jalur. Sumber tanpa isi (misalnya lampiran saja) tidak dikirim ke model.

**Mengapa:** Ingest dan ekstraksi adalah dua status berbeda. Menyimpan sumber sebelum memanggil model memungkinkan retry setelah crash tanpa kehilangan asalnya; klaim Phase 4 menangani dua tab yang memproses sumber sama.

**Verifikasi:** Migration 20260927070000_gmail_handoff.sql diterapkan. Tes memastikan tidak ada panggilan model saat antrean kosong, handoff memakai service yang sama, dan route anonim ditolak. Uji provider nyata menunggu OAuth/API key.

### Increment 5.6a - Lease dan checkpoint scan awal

**Yang dibuat:** State sync per koneksi dan pemilik dengan anchor history, token halaman awal, mode, daftar pending, retry time, status, dan lease 90 detik. Sync awal mengambil dua ID label `FocusOS` per request, menyimpan sumber dahulu, lalu memajukan token halaman dalam transaksi. Ketika halaman terakhir selesai, mode berganti ke history dari anchor yang diambil sebelum scan awal.

**Mengapa:** Crash sebelum checkpoint membuat halaman diulang dengan upsert idempoten; crash setelah checkpoint tidak menghilangkan pesan yang sudah disimpan. Lease mencegah dua tab memajukan cursor bersamaan. Anchor sebelum scan menangkap perubahan yang terjadi di tengah scan saat history diproses berikutnya.

**Verifikasi:** Migration 20260927080000_gmail_sync_state.sql diterapkan. Probe rollback-only membuktikan klaim kedua menjadi busy, checkpoint awal beralih ke history, staging/pengosongan pending menggeser history ID, dan pengguna lain tidak melihat state. Tes service memastikan checkpoint setelah upsert.

### Increment 5.6b - History, retry, dan rescan

**Yang dibuat:** Setelah scan awal, service membaca `history.list` untuk label terpilih. ID dari messageAdded/labelsAdded dideduplikasi dan distage maksimal 30 sebelum fetch; request berikutnya menyimpan maksimal dua sumber, lalu database memotong daftar pending. Cursor history hanya maju setelah daftar pending habis. History 404 memulai scan awal terbatas baru; 429/5xx menjadwalkan retry, tanpa memajukan cursor. Status partial ditampilkan apa adanya.

**Mengapa:** Satu halaman history dapat menyebut lebih banyak ID daripada aman diproses dalam satu fungsi. Staging membuat progress durable, sedangkan replay aman karena upsert sumber idempoten. Reset 404 mengikuti kontrak Gmail ketika history ID kedaluwarsa.

**Verifikasi:** Fixture menguji dedup messageAdded/labelsAdded, staging sebelum pengambilan body, 404 rescan, retry 429, dan checkpoint setelah upsert. Probe SQL 5.6a menegaskan lease, pending, serta RLS. Uji Gmail nyata masih menunggu konfigurasi provider.

### Increment 5.7 - Status dan kontrol sinkronisasi manual

**Yang dibuat:** RPC status membaca koneksi dan checkpoint milik pengguna serta menghitung sumber tersimpan, hasil siap, gagal, dan yang menunggu ekstraksi. FastAPI menyediakan status terautentikasi. Next.js menyediakan proxy server-only dan panel Activity berisi Sync Now/Continue serta Process one source. Setiap klik menjalankan tepat satu halaman sinkronisasi atau satu ekstraksi. Daftar sumber dan status disegarkan setelah operasi, tanpa mengirim token Google ke browser. D9 diputuskan A: tidak ada scheduler/cron.

**Mengapa:** Status dalam database tetap dapat dibaca setelah tab ditutup atau fungsi Vercel selesai. Batas satu unit per request sesuai runtime serverless dan membuat retry, lease, serta partial progress jujur di UI. Pemrosesan model dipisah dari ingest agar kegagalan atau biaya model tidak membatalkan checkpoint Gmail. Browser hanya memanggil proxy terautentikasi; kegagalan provider ditampilkan dengan pesan aman.

**Verifikasi:** Migration `20260927090000_gmail_sync_status.sql` diterapkan. Tes backend memeriksa status tanpa koneksi, RPC terscope pemilik, dan penolakan anonim; tes web memeriksa proxy, token tetap di server, error aman, dan penolakan anonim. Build Next.js lulus. Uji Gmail langsung masih menunggu konfigurasi OAuth dan token di production; uji ekstraksi langsung menunggu OpenAI API key.

**Deployment Phase 5 (2026-09-27):** API deployment dpl_7WCoo4LbtZ1Y1tCgL57J6kkcajz6 and web deployment dpl_9dDTw1iwzSEYAR5xwAjF2kGu2cZD reached READY on the existing aliases. Production smoke checks: API /health 200, web /activity 200, and anonymous Gmail sync status, sync POST, and process-one POST all 401. Vercel environment-name audit found only Supabase URL/publishable key on the API and base app/API/Supabase variables on web; the Google OAuth, token encryption, service-role, and OpenAI keys listed in docs/deployment.md are absent. No live Gmail consent, selected-label sync, or model extraction was performed.

## Phase 6: ketersediaan Google Calendar deterministik

Tidak perlu akun baru. Phase ini memakai project OAuth/Calendar yang sama dan izin baca primary Calendar yang sudah dirancang di Phase 2. Uji provider nyata tetap memerlukan secret OAuth dan koneksi Google yang belum dipasang di Vercel; tes fixture dan endpoint anonim tetap bisa dijalankan tanpa nilai rahasia.

### Increment 6.1 - Kontrak kejadian Calendar

**Yang dibuat:** DTO kejadian timed dan all-day terpisah, membawa ID provider, kalender, judul, status sibuk/transparan, respons diri pada undangan, referensi recurrence, dan waktu observasi. Timed harus memiliki offset UTC dan durasi positif. All-day memakai tanggal akhir eksklusif dan zona IANA yang valid.

**Mengapa:** Payload Google tidak langsung menjadi interval jadwal. Kontrak ini menolak bentuk campuran atau waktu ambigu sebelum algoritma ketersediaan menerima data.

**Verifikasi:** Tes menerima dua bentuk valid dan menolak offset hilang, durasi nol, tanggal akhir salah, zona invalid, serta field campuran.

### Increment 6.2 - Ambil semua halaman Calendar

**Yang dibuat:** Service membaca jendela maksimal 14 hari pada primary Calendar dengan `singleEvents=true` (recurrence diekspansi Google), urutan startTime, maksimal 100 kejadian per halaman, 5 halaman/500 kejadian. Semua halaman memakai filter identik dan nextPageToken; token berulang, timezone berubah, halaman invalid, atau gagal pada halaman kedua membuat seluruh jendela ditolak. Endpoint awal hanya mengembalikan hitungan dan cap waktu, tanpa detail kejadian.

**Mengapa:** Satu halaman tidak membuktikan kalender kosong pada halaman berikutnya. Batas ketat menjaga runtime serverless dan mencegah hasil parsial diperlakukan sebagai waktu bebas.

**Verifikasi:** Tes dua halaman, parameter sama, halaman kedua gagal, cursor berulang, jendela terlalu panjang, dan route anonim ditolak.

### Increment 6.3 - Normalisasi waktu Calendar

**Yang dibuat:** Fungsi murni mengubah kejadian timed menjadi interval UTC dan all-day menjadi tengah malam di zona Calendar sampai tanggal akhir eksklusif. Kejadian recurring yang sudah diekspansi tetap menyimpan ID seri/original start. Kejadian cancelled, transparent, dan undangan diri yang declined tidak menjadi busy. Offset yang bertentangan dengan zona serta waktu lokal ambigu/tidak ada pada transisi DST ditolak.

**Mengapa:** Hari all-day tidak selalu 24 jam saat DST. Menggunakan tanggal dan zona aslinya menjaga batas interval; penolakan waktu ambigu lebih aman daripada mengarang satu jam yang mungkin salah.

**Verifikasi:** Fixture all-day, timed, cross-midnight, recurrence exception, filter nonbusy, perubahan DST, offset salah, dan bentuk campuran lulus.

### Increment 6.4 - Kalkulator waktu kosong murni

**Yang dibuat:** Fungsi menyusun interval jam kerja berdasarkan hari/zona profil, memotongnya pada jendela/deadline, menggabungkan busy interval yang bersentuhan/bertumpuk, lalu mengurangkannya. Mode kontigu memilih slot pertama yang cukup; mode split mengambil bagian berurutan. Hasil memuat kapasitas, alokasi, dan kekurangan menit. Window incomplete, deadline hanya tanggal, serta batas jam kerja yang ambigu saat DST ditolak.

**Mengapa:** Aritmetika jadwal lebih dapat diuji sebagai fungsi deterministik daripada didelegasikan ke model. Kekurangan durasi ditampilkan eksplisit, bukan dibuat seolah tersedia; deadline tanpa jam tidak diam-diam diasumsikan akhir hari.

**Verifikasi:** Tes touching intervals, hari sibuk penuh, kalender kosong, split versus kontigu, deadline, incomplete window, dan batas DST lulus.

### Increment 6.5 - Jadwal Today dan pratinjau availability

**Yang dibuat:** Endpoint baca mengambil profil timezone/jam kerja pengguna, menghitung jendela Today atau tujuh hari lokal, membaca Calendar secara lengkap, menormalisasi busy events, lalu menjalankan kalkulator 6.4. UI Today menyediakan input durasi, pilihan kontigu/split, daftar jadwal sibuk, slot terpilih, kapasitas, shortfall, kalender, timezone, dan fetched-at. Proxy Next.js menjaga bearer server-side, hanya meneruskan parameter allowlist, dan menyembunyikan detail error provider.

**Mengapa:** Pengguna perlu membandingkan hasil algoritma dengan jadwal nyata sebelum agen Phase 7 memakai layanan ini. Pratinjau ini tidak mengajukan persetujuan dan tidak menulis event; hasil lama tidak boleh dianggap aman untuk penulisan nanti, sehingga UI meminta pengecekan ulang sebelum tindakan berikutnya.

**Verifikasi:** Tes API fixture profil/kejadian, kegagalan provider tanpa jadwal parsial, penolakan anonim; tes proxy validasi input/token/error aman; seluruh suite backend dan web serta build Next.js. Perbandingan Calendar nyata menunggu secret OAuth dan koneksi Google produksi yang belum dikonfigurasi.

**Deployment Phase 6 (2026-09-27):** API dpl_EiVrDfB5Be6aztCYcxCTHtbeiyGh dan web dpl_3NTeTRy8nyKWSCZoDXdSn7v4caT6 mencapai READY di alias production yang sama. Smoke test: API /health 200, web Today 200, endpoint Calendar window/availability API dan proxy web tanpa session semuanya 401. Tes backend 160, tes web 46, dan build web lulus. Uji perbandingan dengan Calendar nyata belum dapat dilakukan karena secret OAuth/token production masih belum tersedia; tidak ada klaim bahwa event nyata telah terbaca.

## Phase 7: agen baca/perencanaan dan memori terpilih

Keputusan rekomendasi: D6-B alur bertahap yang dibatasi backend; D11-A konteks per-run tanpa chat permanen; D8-A embed satu memori setelah konfirmasi melalui request terpisah; D12 embedding `text-embedding-3-small` 256 dimensi. Akun baru tidak diperlukan bila OpenAI Platform lama aktif, tetapi API key dengan kuota dan secret OAuth Google produksi belum terpasang; panggilan model/embedding/Calendar langsung akan dinyatakan belum teruji sampai konfigurasi itu ada.

### Increment 7.1 - Batas tool dan ledger run

**Yang dibuat:** Kontrak tool request ketat dengan allowlist awal `tasks.list`, batas argumen dan larangan identity/risk dari model. Tabel command_runs menyimpan status/checkpoint/counter per pengguna; agent_tool_calls hanya menyimpan nama, hash argumen, status, dan kode aman. RPC memulai run secara idempoten, menyimpan checkpoint dengan version compare-and-swap, dan mencatat tool milik pemilik.

**Mengapa:** Model tidak dapat memberi hak baru hanya dengan menulis argumen; setiap eksekusi harus melewati validasi aplikasi. Run per perintah lebih kecil dan mudah dibatasi daripada percakapan permanen. Ledger membuktikan tool yang benar-benar dipanggil tanpa menyimpan token atau isi sensitif.

**Verifikasi:** Tes unknown tool, user_id palsu, limit berlebih, dan hash kanonik; migration serta pemeriksaan owner/versi akan diverifikasi di database.

### Increment 7.2 - Satu roundtrip tool tasks.list

**Yang dibuat:** Adapter Responses API memberi model hanya fungsi `tasks_list`; nama itu dipetakan ke tool internal `tasks.list`. Backend memvalidasi argumen, membaca maksimal 20 tugas open lewat akses pengguna, mencatat requested/succeeded tanpa payload, lalu mengirim hasil ke model untuk turn final. API mengembalikan daftar tugas dari database dan ringkasan deterministik, bukan fakta baru dari teks model. Run dibuat sebelum panggilan model dan disimpan sebagai succeeded/failed dengan request key idempoten.

**Mengapa:** Tool call membuktikan pilihan model tidak menjadi hak akses; database tetap sumber kebenaran. Teks final model tidak boleh mengarang tanggal atau tindakan yang tidak terjadi.

**Verifikasi:** Fixture menerima satu fungsi yang diizinkan, menolak fungsi write palsu, memastikan hasil tool berasal dari task service, dan menolak route anonim. Uji model live menunggu API key.

### Increment 7.3 - Multi-read continuation terbatas

**Yang dibuat:** Endpoint start/get/continue run. Satu continue membaca tugas, langkah berikutnya membaca Calendar primary secara lengkap, dan langkah berikutnya menghitung slot dari snapshot sibuk tersimpan. Setiap langkah menaikkan counter/versi dalam database; maksimal 8 tool call dan 4 model turn. Kalender memakai anchor waktu tetap per run, mencatat 80 busy interval paling banyak, tanpa judul pribadi di checkpoint. Gagal baca atau hasil parsial menandai run gagal dan tidak menghasilkan slot.

**Mengapa:** Vercel tidak menjamin worker berlanjut setelah respons selesai. Checkpoint per langkah membuat tab yang ditutup dapat dilanjutkan secara eksplisit dan mencegah percobaan ulang memulai budget dari nol. Data kalender yang disimpan hanya interval untuk rencana, bukan isi event.

**Verifikasi:** Tes stage/counter, penolakan anonim, kegagalan Calendar tanpa slot palsu, dan terminal planning tanpa tool tambahan. Uji Calendar nyata menunggu secret OAuth.

### Increment 7.4 - Memori yang dikonfirmasi

**Yang dibuat:** Tabel memori punya referensi source/project milik pengguna, source hash, teks fakta, kutipan persis, status active/superseded, dan request key idempoten. RPC SQL memeriksa sumber masih aktif, isi belum kedaluwarsa, quote substring persis, serta project satu pemilik. Activity menyediakan form konfirmasi, daftar memori dari sumber itu, dan tombol tandai usang. Backend serta proxy web tetap mengulang validasi/otorisasi.

**Mengapa:** Hanya sumber yang dipilih dan fakta yang dinilai benar oleh manusia masuk konteks jangka panjang. Fakta usang tidak perlu dihapus diam-diam; status superseded menjaga riwayat keputusan. Konfirmasi selamat meski embedding nanti gagal.

**Verifikasi:** Migration 20260927110000 diterapkan. Probe SQL rollback-only menolak kutipan palsu dan memperlihatkan nol memori saat berperan sebagai pengguna lain. Tes API/proxy dan build web lulus.

### Increment 7.5 - Embedding selektif

**Yang dibuat:** pgvector 256 dimensi pada memori confirmed saja. RPC claim memakai lease 45 detik, status pending/processing/ready/failed, model, dimensi, dan content hash. Tombol Embed/retry memicu satu request setelah konfirmasi; adapter mengirim `text-embedding-3-small` dengan `dimensions=256`, memvalidasi tepat 256 angka finite, lalu menyimpan vector hanya bila lease dan source hash masih cocok. Key OpenAI hanya backend; kegagalan provider menyisakan fakta serta kode aman untuk retry.

**Mengapa:** Tidak semua email atau tugas perlu embedding. Memori yang dikonfirmasi berjumlah kecil, sehingga exact scan cukup dan HNSW tidak perlu. Lease mencegah dua klik menambah biaya bersamaan; hash/model/dimensi mencegah vector lama dipakai untuk teks atau kontrak baru.

**Verifikasi:** Migration 20260927120000 diterapkan. Probe SQL rollback-only membuktikan klaim pertama, busy pada klaim kedua, reuse setelah sukses, dan isolasi pemilik. Tes adapter memeriksa dimensi, key hilang, serta reuse. Live embedding menunggu API key dan kuota.

### Increment 7.6 - Pencarian memori terscope

**Yang dibuat:** RPC search mengambil maksimal lima memori aktif dengan join ke source yang masih hidup dan hash masih cocok; filter owner/project ada di SQL. Exact pgvector cosine scan dipakai bila embedding query tersedia; SQL full-text sederhana menjadi fallback yang diberi label jelas. Tool `memory.search` menjadi tahap baca keempat dalam run, menyimpan hanya lima hasil dan mode pencarian.

**Mengapa:** Similarity tidak boleh melewati batas kepemilikan atau menghidupkan lagi fakta dari sumber yang dihapus/berubah. Pada dataset kecil exact scan lebih mudah dipastikan lengkap daripada index perkiraan. Fallback leksikal menjaga alur baca tetap berguna ketika API key belum tersedia tanpa mengaku sebagai semantic search.

**Verifikasi:** Migration 20260927130000 dan perbaikan 20260927131000 diterapkan. Probe SQL rollback-only membuktikan hasil lexical, semantic dengan vector cocok, nol hasil milik pengguna asing, dan nol setelah source dihapus. Tes service menguji mode fallback, vector, filter project, dan limit.

### Increment 7.7 — kontrak rencana yang bisa diverifikasi

Backend sekarang menerima PlanningResponse v1 yang ketat. Model hanya boleh menunjuk task-N dan slot-N dari snapshot milik server; backend menyelesaikan ID serta waktu blok sendiri, mengecek durasi total, tumpang tindih, tenggat, bukti, dan bentuk klarifikasi/shortfall. Ini mencegah teks model atau handle buatan berubah menjadi rencana yang tampak bisa dijalankan. Semua hasil tetap proposal (`actionable: false`); belum ada penulisan kalender. Tes unit mencakup rencana sah serta slot, total, deadline, overlap dan bukti palsu.

### Increment 7.8 — tahap perencanaan berbasis konteks

Tahap terakhir run menyusun konteks terbatas dari task, slot kalender yang dihitung server, dan maksimal lima memori. Adapter Responses memakai Structured Outputs, `store: false`, tanpa tool tulis. Teks task/memori diperlakukan sebagai data yang tidak dipercaya. Model hanya memilih handle; validator 7.7 menyelesaikan waktu dan ID asli. Hasil `proposed`, klarifikasi, atau waktu tidak cukup disimpan dalam checkpoint terminal. Tahap model memakai CAS lease untuk mencegah panggilan serentak; kegagalan model atau proposal palsu menjadi error aman tanpa blok usulan. Tes mock memeriksa payload, proposal, dan penolakan output palsu. Uji provider langsung menunggu API key runtime.

### Increment 7.9 — halaman perintah dan inspeksi run

Halaman `/agent` menerima perintah, durasi, dan pilihan pembagian blok. Setiap lanjut menjalankan satu tahap sehingga checkpoint dapat direload lewat URL `/agent/{runId}`. Panel memperlihatkan status, jumlah task/event/slot/memori, hasil proposal atau klarifikasi, serta ledger empat tool baca. Route Next.js memproksi request dengan sesi server dan whitelist path; endpoint backend memeriksa kepemilikan run sebelum membaca ledger melalui RLS. Tidak ada tombol approve atau penulisan Google Calendar pada fase ini. Tes mencakup sesi anonim, path, kegagalan upstream, dan akses ledger tanpa run milik pengguna.

### Penutupan Phase 7 — deploy dan batas penerimaan

Pada 2026-09-27, API (`dpl_YefXM6YF9KBUneRzzjHffojMFL3Q`) dan web (`dpl_52wdPVvCWgGeqePyWjLbHAQ7hkoD`) mencapai READY di alias produksi yang sama. Smoke test: API `/health` 200, web `/agent` 200, dan endpoint run tanpa sesi 401. Semua 192 tes backend, 52 tes web, dan build web lulus. Audit nama variabel Vercel memperlihatkan API hanya memiliki URL serta publishable key Supabase; web hanya memiliki empat variabel Supabase/app/API awal. Karena OpenAI key dan kredensial Google integrasi belum ada, belum ada uji live perintah dengan Calendar dan model. Ini batas verifikasi yang nyata, bukan kegagalan tes mock. Setelah variabel privat diisi dan kedua project dideploy ulang, uji sintetik harus dilakukan dari akun yang login.

## Phase 8: persetujuan tepat dan tindakan Calendar

Keputusan D10-A: satu approval per event. Setiap blok rencana punya payload, keputusan, dan hasil terpisah sehingga kegagalan atau retry satu blok tidak menyembunyikan status blok lain. Rencana split memang membutuhkan beberapa persetujuan. Uji provider langsung masih memerlukan secret integrasi Google di Vercel.

### Increment 8.1 — penyimpanan approval immutable

Migration `20260927140000_approval_requests.sql` membuat row approval milik pengguna dengan FK gabungan ke run/task/koneksi pemilik, payload JSON terbatas, hash, ID event stabil, expiry, versi status dan ruang untuk lease/hasil provider. Authenticated hanya mendapat SELECT milik sendiri melalui RLS; trigger menolak perubahan payload/identitas/expiry, dan perubahan status nanti harus lewat RPC. Kontrak Pydantic CalendarAction menolak tamu, kalender selain primary, notifikasi, interval invalid, dan field tambahan. Hash SHA-256 dari JSON canonical mengikat persetujuan ke aksi persis. Migration sudah diterapkan; tes payload backend lulus. Tahap ini belum membuat approval atau memanggil Google.

### Increment 8.2 — proposal Calendar tanpa write

RPC `focusos_propose_calendar_action` membaca satu blok dari run tersimpan milik pengguna, task open, profil, serta koneksi Google dengan scope baca/tulis. Ia membuat satu `approval_requests` berisi payload server-owned, hash JSONB SHA-256, dan Google event ID tetap; pemanggilan ulang blok yang sama mengembalikan ID yang sama. Trigger tambahan memeriksa blok benar-benar cocok dengan slot `free_time` checkpoint dan menolak identitas/kalender/tamu yang berubah. FastAPI mengekspos `POST /agent/runs/{id}/propose-event` dengan satu argumen `block_index`; tidak ada Google HTTP dalam jalur ini. Migration proposal, guard, dan perbaikan batas regex event ID diterapkan. Probe SQL rollback-only memverifikasi pending, replay, dan RLS pengguna lain. Tes backend membuktikan argumen tamu/approved ditolak dan provider tidak dipanggil.

### Increment 8.3 — keputusan manusia per event

RPC list menandai pending yang melewati expiry menjadi expired dan hanya mengembalikan row milik pemilik. RPC keputusan mengunci row, menerima hanya `approve` atau `reject`, menyimpan status/version/decided_at secara atomik, mengulang keputusan sama tanpa perubahan, dan menolak keputusan berlawanan atau pengguna lain. Route FastAPI dan proxy Next.js menerima ID/decision saja; argumen event tidak bisa diganti oleh body keputusan. Kartu di halaman run menunjukkan judul, waktu/zona, primary Calendar, koneksi Google, sumber, bukti, tamu/notifikasi kosong, expiry, dan kontrol approve/reject. Approved status belum melakukan write; hanya menyatakan izin untuk payload tersimpan.

### Increment 8.4 — preflight sebelum tindakan

Service preflight memuat ulang approval milik pengguna, memeriksa status/expiry serta identitas payload, versi/status/judul/sumber/deadline task saat ini, scope Google read+write, dan zona/jam kerja profil. Ia mengambil ulang Calendar lengkap dari sekarang sampai akhir blok, menghitung interval bebas secara deterministik, dan menolak blok yang telah sibuk atau keluar jam kerja. Kegagalan provider dibedakan dari stale/conflict agar retry tidak mengarang sukses. Pada increment ini preflight belum terhubung ke insert Google. Tes fixture membuktikan slot bersih lulus dan task berubah, scope dicabut, approval ditolak/kedaluwarsa, atau event sibuk baru semuanya ditolak. Probe SQL rollback-only tambahan memeriksa keputusan sama idempoten dan keputusan berlawanan ditolak.

### Increment 8.5 — adapter insert dan rekonsiliasi Google Calendar

Adapter server-only menyusun body event dari payload approval yang telah dibatasi: ID Google stabil, judul, waktu/zona, tanpa attendee, reminder default dimatikan, `sendUpdates=none`, dan private marker `focusos_payload_hash`. Ia selalu mencoba `events.get` dengan ID itu sebelum insert. Jika respons insert hilang, 409, atau 5xx, ia membaca ulang ID yang sama dan menerima sukses hanya bila marker, ID, judul, waktu, serta absennya tamu cocok persis. Marker berbeda menjadi conflict; hasil yang belum dapat dibuktikan menjadi unknown, 429 menjadi deferred, dan 401/403 meminta reconnect. Tes HTTP mock mencakup insert, timeout sebelum/sesudah write, 409 cocok/tidak cocok, dan rate limit. Adapter belum dipanggil oleh route UI pada increment ini. Google mengizinkan custom ID base32hex tetapi collision tidak dijamin terdeteksi saat insert; marker dan rekonsiliasi membantu mendeteksi hasil yang salah ([Google Events reference](https://developers.google.com/workspace/calendar/api/v3/reference/events)).

### Increment 8.6 — klaim dan eksekusi satu approval

RPC `focusos_claim_approval_execution` dan `focusos_finish_approval_execution` hanya dapat dijalankan service_role; FastAPI lebih dahulu memverifikasi JWT pengguna lalu mengirim user ID itu ke RPC yang mencocokkannya dengan owner approval. Claim memakai lock dan lease, mengembalikan flag `claimed` sehingga request kedua tidak boleh memanggil Google. Satu pemilik hanya boleh punya satu action berstatus executing; unknown action harus direkonsiliasi sebelum action lain berjalan. Setelah claim, backend memakai stable ID: GET dulu, lalu preflight kalender baru, lalu INSERT. Reconcile setelah respons hilang dapat menyimpan `succeeded` hanya dengan ID/marker provider yang cocok. Konflik, stale, rate limit, token tidak tersedia, dan unknown mempunyai status/kode aman terpisah. SQL finalizer memakai expected status version; hanya proof event ID yang sama yang boleh disimpan sebagai sukses. Probe SQL rollback-only menguji claim pertama, penolakan claim kedua, finalisasi dan replay terminal. Tes backend menguji pemenang claim, request kedua tanpa provider, unknown tanpa sukses, dan penolakan anonim. Uji satu event nyata belum mungkin karena credential produksi integrasi Google belum ada.


### Increment 8.7 — hasil tindakan dan audit yang jujur

Migration `20260927144000_approval_audit.sql` menambah jejak transisi approval append-only. Trigger mencatat status, versi, waktu, dan kode aman setiap kali approval dibuat atau statusnya berubah; row audit hanya dapat dibaca pemilik lewat RLS. Audit tidak menyimpan token maupun isi event. Endpoint `GET /agent/runs/{id}/audit` menggabungkan run, ledger tool baca, approval, dan transisi tersimpan, lalu menghitung status tindakan terpisah dari status planning. Dengan begitu `proposed`, `approved_not_executed`, `unknown`, `partially_completed`, dan `completed` tidak tertukar. Halaman run menampilkan hasil per blok, tautan Google hanya bila provider mengembalikan proof yang cocok, serta riwayat keputusan/tindakan. Tombol eksekusi ulang untuk status unknown melakukan rekonsiliasi ID stabil sebelum kemungkinan write. UI tidak boleh mengubah payload yang disetujui.

Migration diterapkan dan probe SQL rollback-only memverifikasi jejak serta klaim/finalisasi. Tes backend memeriksa status turunan dan anonimitas; tes proxy memeriksa path audit serta bahwa body event palsu dari browser tidak diteruskan. Build web lulus. Uji end-to-end Google nyata belum dapat dilakukan sampai kredensial integrasi private terpasang.

### Penutupan Phase 8 — batas penerimaan live

Semua increment 8.1–8.7 telah diimplementasikan, dimigrasikan, dan diuji dengan fixture, mock HTTP, serta probe SQL rollback-only. Kode memisahkan empat tahap: proposal server-owned, keputusan manusia atas payload immutable, claim/preflight/insert provider, dan audit hasil. Jalur gagal/timeout menyimpan `unknown` atau kode aman bila bukti event tidak ada; hanya event dengan stable ID dan marker yang cocok bisa dianggap sukses. Belum ada klaim bahwa event nyata berhasil dibuat atau alur Gmail → task → command → approval → Calendar telah teruji end-to-end. Itu memerlukan kredensial Google integrasi, key enkripsi token, Supabase service-role key, OpenAI API key/quota, consent OAuth, dan satu akun uji yang login. Tidak ada account baru yang wajib dibuat bila project Google Cloud, Supabase, OpenAI Platform, dan dua project Vercel yang sudah ada masih digunakan. Setelah secret terpasang, deploy ulang API dan web, sambungkan ulang Google dengan scope baca/tulis Calendar, lalu lakukan satu event sintetik dan cocokkan event ID, judul, waktu/zona, tidak adanya tamu, serta tautan provider; ulangi execute untuk membuktikan tidak ada event kedua.


Phase 8 deploy produksi 2026-09-27: API `dpl_Dc14A568vsCLW4G6vyxyfY9WEkWA` dan web `dpl_4FtWd3C46736RJEukMhS6bXVwWLK` berstatus READY pada alias lama. Smoke test API `/health` 200, web `/agent` 200, dan route audit/eksekusi/list approval tanpa sesi 401. Seluruh 212 tes backend, 55 tes web, dan build web lulus. Audit *nama* env production menunjukkan API masih hanya mempunyai URL/publishable Supabase; web mempunyai empat env dasar Supabase/app/API. Secret Google integration, key enkripsi token, service-role key, dan OpenAI key belum ada, sehingga alur event Google sungguhan tetap belum teruji. Deploy pertama API sempat ditolak Vercel sebagai `Not authorized`; retry dengan `--yes` berhasil tanpa perubahan kode.


## Phase 9: evaluasi, recovery, dan kesiapan rilis

### Increment 9.1 — dataset sintetis held-out

`evals/cases.jsonl` berisi 24 kasus sintetis dengan jam/zona acuan tetap: 8 extraction, 4 ambiguitas, 4 scheduling, 4 policy, dan 4 adversarial/ownership. Tiap baris mencatat fakta/task yang diharapkan, kutipan evidence yang harus ada dalam sumber, serta tindakan terlarang. Enam contoh pengembangan terpisah ada di `evals/dev.jsonl`; kasus held-out tidak dipakai untuk tuning. Validator memeriksa distribusi, keunikan, format tanggal, dan kutipan literal. Ini baru label, belum skor model.


### Increment 9.2 — runner evaluasi extraction opt-in

`evals/run.py` memanggil service `extract_structured` yang sama dengan aplikasi untuk 16 kasus extraction/ambiguity/adversarial memakai jam/zona tetap. Mode `--dry-run` hanya memvalidasi dan menulis status `skipped`, tanpa call provider atau skor palsu; `--live` eksplisit memerlukan OpenAI API key. Observasi lokal (di-ignore Git) berisi versi model/prompt/schema, status/kode gagal, latency, usage, title/deadline task sintetis, dan hash evidence; tidak berisi body email, kutipan mentah, token, atau respons provider. Tes memverifikasi dry-run tidak memanggil model dan provider yang tidak tersedia tercatat sebagai gagal. Live run menunggu key API yang belum tersedia.


### Increment 9.3 — scoring dan laporan agregat

`evals/score.py` memasangkan task satu-ke-satu berdasarkan judul normalized exact, lalu menerima padanan semantik hanya bila reviewer menulis judgment eksplisit per pasangan. Skor menghitung match, deadline kind/value, fingerprint evidence, task hilang, dan task ekstra; call model gagal tetap menjadi denominator expected. Status `skipped` tidak diperlakukan sebagai keberhasilan atau kegagalan model. Laporan baseline statis `docs/evaluation.md` menyatakan 0/16 live, 16/16 skipped dan akurasi belum diukur. Tes membuktikan exact match, gagal, variasi semantik yang memerlukan judgment, dan dry-run tanpa angka akurasi. Live metric menunggu OpenAI API key.


### Increment 9.4 — gerbang regresi keamanan dan recovery

`evals/safety_gate.py` menjalankan suite terpilih untuk tool allowlist/injection, budget continuation, proposal dan preflight, approval belum disetujui, satu claim winner, timeout/lost response, marker konflik, serta audit unknown. Tes baru memastikan approval pending tidak mengambil token dan tidak menyentuh adapter Google. Gerbang ini berjalan dengan provider mock dan tidak mengklaim uji Google nyata. Semua suite terpilih lulus.


### Increment 9.5 — disconnect, retensi, dan hapus data impor terpilih

Migration `20260927150000_data_lifecycle.sql` menambah RPC owner-scoped untuk disconnect Google dan menghapus tepat satu source Gmail yang dipilih. Disconnect mengubah status koneksi, membuang ciphertext refresh/access token serta cursor sync, mengosongkan scope/email metadata, menandai approval pending/approved stale, dan mengubah execution yang mungkin sedang berjalan menjadi unknown; event Google yang sudah ada tidak dihapus. Penghapusan source membersihkan task yang linked, run checkpoint/result yang mengandung ID source, dan source; FK cascade membersihkan extraction result, agent extraction run, memori/embedding, dan approval/action audit dari run terkait. Run lain tetap ada. Kedua tindakan dipicu eksplisit lewat UI, bukan lewat GET atau saat migration diterapkan. Migration `20260927150100_expire_unreviewed_payload.sql` memperluas cleanup lazy terbatasi maksimal 100 source/request: setelah 30 hari body sumber dan payload extraction yang belum dikonfirmasi dikosongkan. Task dan memori yang telah dikonfirmasi tetap ada sampai source terkait dihapus eksplisit.

FastAPI menyediakan DELETE koneksi dan DELETE source ID yang tervalidasi. Proxy Next.js memakai sesi server dan whitelist path; UI Settings menyediakan tombol disconnect, Activity menyediakan tombol hapus hanya pada Gmail source. Probe SQL rollback-only membuktikan satu source/task/run terkait hilang, run tak terkait bertahan, token hilang saat disconnect, dan body/payload kedaluwarsa dibersihkan. Tes API/proxy serta build web lulus. Karena credential Google live belum ada, reconnect nyata dan efek pada sync/provider tidak dapat diuji langsung. Request yang sudah berada di luar database saat disconnect mungkin masih mencapai Google; hasilnya ditandai unknown bila proof/finalisasi tak dapat dipastikan, sehingga pengguna harus memeriksa Calendar sebelum mencoba ulang.


### Increment 9.6 — CI, deploy, smoke, dan panduan demo

Workflow `.github/workflows/ci.yml` menjalankan tes API/web/eval, validasi 24 kasus, dry-run dan scorer tanpa key, safety gate, serta build Next.js pada Linux tanpa secret. Run pertama gagal karena skrip npm backend memakai path Python Windows; workflow diperbaiki memakai `python -m unittest` dan [run CI berikutnya berhasil](https://github.com/Felixsimbolon/FocusOS/actions/runs/36298773031). `docs/demo.md` merinci setup akun/env, urutan demo sintetik, cara membandingkan event Google, kontrol data, serta batas saat ini; halaman `/agent` menautkan laporan evaluasi statis. Rangkaian lokal lulus: 216 tes backend, 58 tes web, 5 tes evaluator, safety gate, validasi 24 kasus, dan build web. Dry-run menulis 16/16 skipped; akurasi tetap belum diukur.

Migration 9.5 terpasang. Deploy API `dpl_5s6k6nHCXXruEK2puumZz4K81v6f` dan web `dpl_HALEESKPyjPWrgZ635mvG9g3xsHN` READY pada alias produksi lama. `evals/hosted_smoke.py` memverifikasi API `/health` dan web `/agent` 200, lalu `/api/me`, audit run, disconnect, hapus source, dan execute approval tanpa sesi 401. Smoke ini tidak memakai cookie/token dan bukan uji browser login. Nama env Vercel yang terakhir diaudit masih hanya variabel dasar Supabase/app/API; local `FOCUSOS_OPENAI_API_KEY` juga tidak tersedia. Karena itu 9.6 sebagai **penerimaan end-to-end** belum selesai: model live, hosted auth terbaru, reconnect Google, dan satu event Calendar nyata tetap pending. Tidak ada klaim bahwa final MVP acceptance gates telah lulus.


### Audit penutupan phase terakhir — pekerjaan yang masih kurang

`plan.md` berakhir pada Phase 9; tidak ada increment Phase 10. Audit ulang pada 2026-09-27 menegaskan [CI commit akhir Phase 9 berhasil](https://github.com/Felixsimbolon/FocusOS/actions/runs/36298871570), alias produksi masih merespons smoke 7/7, dan env Vercel integrasi tetap belum ada (API dua nama dasar, web empat nama dasar). Dokumen `docs/remaining-work.md` memetakan enam gap: secret, consent Google, skor extraction live, demo Gmail→Calendar, browser/lifecycle live, dan semantic memory live. Untuk setiap gap dicatat tindakan serta bukti lulus yang perlu dikumpulkan. Kotak 9.6 dan final acceptance tetap terbuka; tidak ada event Google atau skor model yang direka dari mock.

## Migrasi provider AI ke Gemini (27 September 2026)

Setelah key Gemini dibuat, adapter ekstraksi, planner, fungsi baca tugas, dan embedding dipindah dari OpenAI Responses/Embeddings ke Gemini GenerateContent/EmbedContent. Backend memakai GEMINI_API_KEY; model generasi gemini-3.5-flash-lite dan embedding gemini-embedding-2 256 dimensi. Prompt versi 2; kontrak schema versi 1 tetap. Validasi bukti, owner, batas panggilan, dan pemeriksaan keluaran tetap di backend. Migration baru mengubah metadata provider dan fungsi pgvector, serta mengembalikan embedding lama ke pending karena model vektor berbeda; fakta terkonfirmasi tidak dihapus. Tes mock backend 217 lulus. Migration produksi, key Vercel, panggilan provider live, dan evaluasi kualitas masih pending. Setup lengkap ada di [gemini-setup.md](gemini-setup.md).

## Perbaikan sesi lokal untuk route aksi (27 September 2026)

Saat /api/me sukses tetapi Save source dan aksi lain menjawab Authentication required, pemeriksaan token aksi ternyata membaca session.user.id dari cookie Supabase yang dikonfigurasi tokens-only. Server sekarang membaca access token dari sesi, memverifikasi token yang tepat dengan Supabase Auth, lalu meneruskannya ke FastAPI. Route profil memakai helper yang sama agar hasil login dan izin aksi konsisten. Uji regresi cookie tokens-only dan penolakan token invalid lulus (5 tes auth-session); typecheck web lulus. Uji ulang melalui browser dengan sesi pengguna masih perlu dilakukan.

## Diagnostik provider Gemini saat ekstraksi gagal (27 September 2026)

Ketika UI menampilkan provider_error, adapter kini mencatat hanya status HTTP, status error resmi Gemini, nama model, atau tipe error transport ke terminal FastAPI. Isi request, respons lengkap, dan API key tidak dicatat. Ini membedakan key/permission, model, kuota, schema request, dan gangguan jaringan saat uji lokal.

## Perbaikan schema Gemini pada request ekstraksi (27 September 2026)

Uji lokal mengembalikan HTTP 400 INVALID_ARGUMENT dari Gemini. Audit schema menemukan keyword const yang berasal dari Pydantic pada schema_version, sedangkan subset JSON Schema Gemini mendukung enum. Adapter ekstraksi dan planner kini mengubah const menjadi enum satu nilai sebelum mengirim request. Validasi Pydantic lokal tetap memakai kontrak aslinya. Panggilan Gemini live setelah perubahan masih perlu dicoba ulang; pembatasan ekstraksi database adalah lima run per sepuluh menit.

## Audit lanjutan HTTP 400 Gemini (27 September 2026)

Setelah penggantian const ke enum, panggilan ekstraksi masih mendapat HTTP 400 INVALID_ARGUMENT. Ini belum cukup untuk menyimpulkan schema bermasalah: dokumentasi Google memakai status yang sama untuk API key tidak valid. Adapter kini mencatat reason ErrorInfo dan field violation resmi bila tersedia, tanpa pesan error mentah. Probe lokal privat di .temp/gemini_probe.py mencoba model lookup, generate sederhana, schema sederhana, lalu schema FocusOS dengan input sintetis; outputnya hanya status, reason, field, dan kategori error. Hasil probe pengguna masih pending.

## Perbaikan MIME output JSON Gemini (27 September 2026)

Probe dengan key pengguna membuktikan model lookup dan generate sederhana HTTP 200, tetapi schema JSON sederhana HTTP 400 pada generation_config.response_format.text.mime_type. Field ini memakai enum APPLICATION_JSON pada GenerateContent REST; adapter sebelumnya mengirim string MIME application/json. Nilai adapter dan ekspektasi tes diubah ke APPLICATION_JSON. Hasil panggilan setelah perubahan masih perlu diverifikasi melalui probe lokal; tidak ada key yang dicatat atau disimpan di repo.


## Perbaikan visibilitas tugas hasil extraction (27 September 2026)

Pada uji source sintetis, dua kandidat dikonfirmasi. Tugas tanpa deadline muncul di Home, sedangkan tugas "Send the project brief" bertenggat 2 Oktober 2026 tidak muncul karena Home hanya memuat Today: tugas jatuh tempo hari ini, terlewat, atau tanpa deadline. Setelah tugas Today ditandai selesai, Home terlihat kosong walaupun tugas masa depan masih aktif. Home kini memuat daftar Upcoming dari task terbuka dan menampilkan task masa depan di kartu yang sama, termasuk bukti source dan aksi edit/complete. Daftar task terbuka dibatasi 100 terbaru; UI memberi tahu bila hasil terpotong.

Halaman Activity sebelumnya hanya menyimpan status Confirmed dalam state browser. Setelah reload tombol Confirm task kembali muncul meski database sudah menyimpan task dengan identitas extraction/local_ref yang unik. Respons extraction sekarang membaca local_ref task terkonfirmasi milik pengguna, termasuk task berstatus done, lalu kartu review menampilkan status Confirmed dari data tersebut. Tidak perlu migration baru. TypeScript check dan 60 tes web lulus; sintaks Python lulus. Tes backend untuk kasus reload ditambahkan tetapi run-nya ditolak auto-review sesi, sehingga masih perlu dijalankan bila diizinkan. Perlu uji ulang browser lokal setelah restart API untuk membuktikan brief muncul di Upcoming dan kedua kandidat tetap Confirmed setelah reload.


## Pencarian memori langsung tanpa Calendar (27 September 2026)

Uji lokal menunjukkan run Planning agent berada di status waiting/start setelah pertanyaan fakta diajukan. Ini perilaku staged run: tombol Continue run baru mengeksekusi pembacaan task, Calendar, slot bebas, lalu memory.search sebelum proposal. Planning agent dirancang untuk menyusun blok kerja dan bukan antarmuka tanya jawab fakta; arahan sebelumnya untuk menguji memori lewat pertanyaan di /agent kurang tepat, terutama bila Google Calendar belum terhubung.

Untuk menguji memori yang sudah dikonfirmasi dan di-embed tanpa ketergantungan Calendar, FastAPI kini menyediakan POST /memories/search memakai fungsi owner-scoped search_memories yang sudah dipakai agent. Proxy Next.js hanya mengizinkan path search yang dikenal dan meneruskan token sesi server. Halaman /memories menerima query, menampilkan mode semantic atau keyword fallback, fakta yang cocok, kutipan bukti, serta tautan source. Ini menampilkan hasil retrieval, bukan menghasilkan jawaban chat atau event Calendar. Panduan Gemini dan demo diperbarui. TypeScript check, sintaks Python, dan git diff check lulus; browser dengan sesi login dan provider live masih perlu diuji.

### Perubahan alur Activity — tangkap tugas dan memori otomatis

Sebelumnya sinkronisasi Gmail hanya mengimpor sumber, tombol "Process one source" hanya mengekstraksi kandidat, dan pengguna harus menekan "Confirm task" serta mengisi "Confirm memory". Alur ini sekarang disambungkan: saat sumber manual disimpan, API langsung menjalankan ekstraksi dan menyimpan semua tugas serta fakta/keputusan yang punya kutipan sumber. Saat Gmail disinkronkan melalui Activity, browser meneruskan sumber yang menunggu ke endpoint pemrosesan satu per satu; endpoint yang sama langsung menyimpan hasilnya. Karena batas ekstraksi lima klaim per sepuluh menit dan batas waktu request, satu klik memproses maksimal lima sumber; bila masih ada antrean, Activity menampilkan bahwa sinkronisasi perlu dilanjutkan. Kegagalan pada satu sumber menghentikan putaran agar sumber gagal tidak diproses berulang dalam satu klik.

Penyimpanan tugas tetap menggunakan RPC konfirmasi lama yang memeriksa kepemilikan, hash sumber, dan kutipan bukti. Deadline yang unresolved menjadi tugas tanpa tanggal, bukan tanggal tebakan. Memori hanya dibuat dari fakta hasil ekstraksi yang punya kutipan persis dalam teks sumber. Request key memori diturunkan secara deterministik dari identitas dan isi sumber serta fakta, sehingga retry tidak membuat duplikat. Embedding untuk pencarian dijalankan otomatis oleh UI setelah penyimpanan melalui endpoint memori yang sudah ada. Jika embedding gagal, memorinya tetap tersimpan dan statusnya terlihat; pemrosesan sumber dapat dicoba lagi. Event Calendar tidak dibuat otomatis karena jalur write Calendar tetap membutuhkan persetujuan terpisah.

Halaman Today juga memakai navigasi kartu yang lebih jelas menuju Activity, agent, memori, dan settings, dengan tampilan yang selaras. Activity kini menampilkan form "Save and organize", tombol "Sync & organize email", daftar sumber, tugas dan memori tersimpan, kutipan bukti, serta status gagal/retry. Sumber lama yang sudah mempunyai ekstraksi tetapi belum tersimpan dicoba untuk direkonsiliasi saat dibuka. Tidak ada migration atau env baru. Build Next.js, 60 tes frontend, dan suite backend dan tes rute baru lulus. Uji live Google/Gemini/Supabase masih perlu dilakukan dari browser lokal untuk memastikan latensi dan izin akun nyata.

### Diagnostik proposal Calendar saat uji end-to-end

Saat tombol Prepare approval mengembalikan 409, proxy web sebelumnya selalu berkata "Connect Google Calendar or save scheduling preferences". Pesan itu tidak akurat karena RPC proposal juga menolak rencana kedaluwarsa, task berubah, deadline hanya tanggal, slot lewat, atau blok yang tak cocok. Backend kini memetakan hanya alasan SQL yang dikenal ke kode aman; Next.js menampilkan langkah pemulihan spesifik tanpa membocorkan detail PostgREST atau data pribadi. Kegagalan database yang tidak dikenal menjadi 503 generik. Tes backend proposal dan tes proxy agent lulus; pengecekan tipe TypeScript lulus. Pada akun live, izin Calendar write tetap harus diberikan melalui Settings → Google connections sebelum membuat approval.

### Perbaikan proposal Calendar: format UTC Z versus +00:00

Uji nyata Prepare approval langsung gagal dengan kode plan_stale meski run baru dibuat. Penyebabnya bukan waktu kedaluwarsa: checkpoint free_time diserialisasi Pydantic sebagai UTC berakhiran Z, sedangkan blok hasil planner memakai isoformat Python berakhiran +00:00. Trigger approval membandingkan kedua string secara literal. Migrasi 20260927170000_calendar_slot_instant_match.sql mengganti hanya perbandingan awal dan akhir slot menjadi perbandingan timestamptz; validasi identitas, pemilik, task, payload, dan batas waktu tetap dipertahankan. Migrasi diterapkan ke Supabase tertaut. Dry run berikutnya menyatakan tidak ada migration tertunda; query baca saja pada database tertaut mengembalikan same_instant=true dan guard_uses_timestamp_comparison=true. Tes kontrak planning dan proposal lulus. Run lama yang belum kedaluwarsa dapat dicoba lagi tanpa membuat rencana baru; jika kedaluwarsa, buat run baru.

### Perbaikan audit pada panel approval Calendar

Setelah proposal Calendar berhasil dibuat, panel memuat daftar approval dan audit secara paralel. Query audit memakai filter user_id, padahal role authenticated sengaja tidak punya hak SELECT pada kolom tersebut; kebijakan RLS sendiri sudah membatasi baris ke pemilik. Akibatnya PostgREST menolak query, FastAPI salah mengubah gangguan database menjadi 404, dan Promise.all di UI menyembunyikan approval yang mungkin sudah tersimpan. Query audit sekarang memfilter run_id setelah memastikan run milik pemanggil, lalu mengandalkan RLS untuk isolasi pengguna. API membedakan run yang benar-benar tidak ada (404) dari audit yang gagal dibaca (503). UI tetap memperlihatkan approval jika audit sementara gagal. Tes audit, agent continuation, proxy agent, dan pemeriksaan tipe TypeScript lulus. Tidak perlu migration baru.

### Planning agent: satu submit langsung membuat blok Calendar (27 September 2026)

Alur planning sebelumnya berhenti pada setiap tahap baca dan meminta klik Continue, lalu setiap blok perlu Prepare approval, Approve, dan Create event. Kini form /agent mengirim `auto_calendar: true` dan browser meneruskan tahap task, Calendar, free-time, memory, serta planner secara berurutan. Setelah rencana berhasil, browser memproses setiap blok satu per satu lewat endpoint `/agent/runs/{run_id}/blocks/{block_index}/auto`. Halaman menampilkan progres, alasan kegagalan yang aman, dan pada blok yang berhasil tanggal, jam menurut zona waktu profil, serta tautan Google Calendar. Reload tautan run melanjutkan run otomatis yang belum selesai dan membaca event yang telah dikonfirmasi. Run lama tanpa flag otomatis tidak melakukan penulisan Calendar.

Penulisan event tetap memakai proposal yang dibentuk database dari run tersimpan, validasi pemilik, izin Google Calendar write, pemeriksaan task dan slot terkini, serta event ID deterministik untuk rekonsiliasi retry. Migrasi `20260927180000_automatic_calendar_actions.sql` menambahkan `authorization_mode` pada approval dan audit, lalu RPC pemilik mengubah proposal valid menjadi approved secara otomatis hanya untuk run yang dimulai dengan flag tersebut. Audit merekam mode automatic; alur ini tidak memalsukan keputusan manual. Jika satu dari beberapa blok gagal, blok yang sudah berhasil tetap terlihat dan halaman memberi peringatan tentang sisanya. Tidak ada env baru; koneksi Google yang sudah ada harus memiliki Calendar write scope.

Migrasi diterapkan ke Supabase tertaut setelah dry-run. Validasi: 234 tes backend, 62 tes frontend, dan Next.js production build lulus. Konektivitas Calendar pada sesi pengguna nyata belum diuji dari alat ini; pengguna dapat menguji dengan submit rencana baru di /agent dan memeriksa event serta tautannya.
### Home: kalender deadline dan penyegaran antarmuka (27 September 2026)

Daftar Upcoming lama diganti dengan panel Deadlines: daftar tugas yang akan jatuh tempo dan kalender bulanan dalam satu area. Tanggal yang mempunyai tugas terbuka diberi titik merah. Hover, fokus keyboard, atau klik tanggal menampilkan tugas pada hari itu; navigasi bulan dan tombol Today memudahkan melihat deadline lebih jauh. Deadline bertipe tanggal tetap pada tanggal aslinya, sedangkan deadline bertipe waktu dikelompokkan menurut zona waktu profil agar cocok dengan pembagian Today. Filter Upcoming sekarang membandingkan tanggal deadline dengan hari lokal pengguna; tugas tanpa deadline atau yang sudah lewat tetap berada di Today dan tidak salah masuk Upcoming. Daftar dibatasi oleh API pada 100 tugas terbuka dan UI memberi keterangan bila hasil terpotong.

Form tambah tugas dan project ditempatkan dalam composer yang dapat dibuka, sehingga daftar kerja dan deadline lebih mudah dipindai. Gaya home, kartu, tombol, form, halaman agent/settings, serta keadaan fokus dan layar kecil dirapikan dengan CSS yang konsisten. Kalender ini adalah tampilan deadline task FocusOS di home; ia tidak membuat event deadline baru di Google Calendar. Tidak ada migrasi atau env baru. Uji pengelompokan timezone, seluruh tes web, pemeriksaan tipe, dan build produksi dijalankan; sesi browser pengguna tetap perlu dipakai untuk pemeriksaan visual akhir.
### Task manual masuk Memory, deadline dua per halaman (28 September 2026)

Form Add a task sekarang menyimpan task beserta satu memory dari isi form dalam satu transaksi database. Migrasi `20260927190000_manual_task_memory.sql` menambah RPC pemilik `focusos_create_task_with_memory`: ia memakai idempotency key task yang sudah ada, membuat sumber bertipe `task` berisi judul/deskripsi/deadline asli, menyimpan kutipan judul sebagai bukti memory, menghubungkan source ke task, lalu mengembalikan `memory_id`. Jika request diulang, task, source, dan memory yang sama dikembalikan; jika langkah apa pun gagal, transaksi dibatalkan. Source task tidak dikirim ke ekstraksi Activity agar tidak membuat task duplikat. Memory langsung tersedia untuk pencarian kata kunci; browser meminta embedding Gemini setelah penyimpanan untuk pencarian semantik. Jika embedding gagal, task dan memory tetap tersimpan.

Di home, lingkaran hijau pada teks status login dihapus. Daftar Upcoming/Deadlines diurutkan menurut urgensi prioritas (high, normal, low), lalu tanggal deadline lokal pengguna dan waktu aktual di dalam tiap prioritas. Daftar hanya memperlihatkan dua task per halaman; navigasi Previous/Next muncul jika jumlahnya lebih dari dua. Kalender tetap menunjukkan seluruh deadline yang dimuat.

Migrasi diterapkan ke Supabase tertaut. Probe database dalam transaksi yang di-rollback membuktikan satu request membuat task, source, dan memory, lalu retry mengembalikan ID yang sama tanpa duplikasi. Suite backend (234 tes), suite web (65 tes), dan build Next.js lulus. Tidak ada environment variable baru.
Koreksi urutan Upcoming: prioritas high ditampilkan sebelum normal dan low; deadline terdekat menentukan urutan di dalam prioritas yang sama. Pagination tetap dua task per halaman.


### Rilis produksi setelah perubahan Activity, planning, dan deadline (28 September 2026)

Commit `e8165b0` di-push ke GitHub `main`. Karena Git-triggered deploy belum disambungkan, API dan web dideploy lewat Vercel CLI dari direktori masing-masing. API deployment `dpl_FfwPE4Mt3wUJqr4754XR94iEh91H` dan web deployment `dpl_61snW6zQoagJktBVWWQzwscuQU9F` mencapai READY; alias tetap `https://focusos-api.vercel.app` dan `https://focusos-web-five.vercel.app`. Sebelum deploy, dry-run Supabase menyatakan seluruh migration sudah up to date. Pengguna meminta lanjut deploy tanpa mengulang tes; pemeriksaan build dilakukan oleh Vercel saat deploy. Audit nama env produksi menunjukkan API hanya mempunyai URL/publishable key Supabase, sedangkan web masih hanya mempunyai empat env dasar. Secret Gemini, Google integration, token encryption, dan service-role masih harus diisi di Vercel lalu kedua project di-deploy ulang. Belum ada klaim uji browser ber-login atau event Google nyata untuk rilis ini.


### Pencarian memori menjadi jawaban berbukti

Demo produksi menunjukkan pertanyaan tentang nama kode proyek mengembalikan dua memori bertopik sama, bahkan fakta rapat dapat muncul sebelum fakta Aurora. Retrieval semantik lama hanya mengurutkan kemiripan vektor dengan ambang 0,2; urutan itu tidak membuktikan sebuah fakta menjawab pertanyaan. Evaluator lama juga belum mengukur relevansi retrieval.

Untuk pencarian yang meminta jawaban, API kini memakai lima kandidat yang tetap difilter berdasarkan pemilik dan source aktif, lalu meminta Gemini memilih tepat satu indeks yang langsung menjawab atau -1 bila tidak ada. Server mengembalikan teks fakta dan kutipan bukti yang sudah tersimpan; model tidak menulis jawaban bebas. Jika seleksi gagal, UI menyatakan jawaban tidak dapat diverifikasi dan membiarkan kandidat dapat diperiksa. Tool memory.search milik planning agent tetap memakai retrieval lama tanpa panggilan seleksi tambahan. Halaman /memories memprioritaskan satu jawaban dengan tautan sumber dan menyembunyikan kandidat lain dalam bagian detail. Header halaman juga dirapikan mengikuti pola Activity.

Tes backend memeriksa fakta yang dipilih, pertanyaan tanpa jawaban, kegagalan provider, dan indeks model tidak valid. TypeScript check lulus. Keakuratan seleksi Gemini pada sesi produksi masih perlu diuji dengan pertanyaan positif dan negatif setelah web/API baru dideploy.


Rilis pencarian berbukti: commit `e6e3313` telah di-push ke `main`; API deployment `dpl_5zqE2KE3ahLC4xGfB2kUGcmskHWi` dan web deployment `dpl_6TCatvRrv9qJX5F2zm6y9nPwUhwb` mencapai READY pada alias produksi lama. Setelah rilis, GET API `/health` dan GET web `/memories` mengembalikan 200, sedangkan POST `/api/memories/search` tanpa sesi mengembalikan 401. Suite API 238 tes, suite web 65 tes, TypeScript check, dan build web lulus. Pemilihan Aurora oleh Gemini pada sesi pengguna masih menunggu uji browser.


## Personal product - days 1-3: deterministic planning (2 October 2026)

**Problem and outcome:** Planning could fail because the form silently requested 60 minutes, free slots were selected before requested-day/deadline constraints, and model output had to reproduce titles and arithmetic totals exactly. Plans now use a narrow Gemini intent selection followed by deterministic server allocation; explicit durations/days are grounded in the original command, and missing/conflicting constraints produce actionable clarification. A five-minute write buffer, whole-minute boundaries, 15-minute split minimum, preserved Calendar revalidation, and safe replay prevent stale/invalid blocks from becoming events. These are reproduced failure classes; the exact cause of a historical production run is not claimed without its logs.

**Implementation:** Added intent schema, command constraint grounding, deterministic compiler, optional duration override UI, safe feedback, strict input options, and request-options replay protection. Existing plan/checkpoint/Calendar action contracts remain compatible; no database migration or additional approval step is required. Expired run state is derived from the stored expiry because SQL does not allow expired-run updates. Background execution remains for the later worker step.

**Automatic verification:** 276 backend tests, 76 web tests, and 7 evaluator tests passed. Eight synthetic planning regression cases passed; the report explicitly labels mock selection and makes no live-model accuracy claim. API workflow tests cover extraction, capture, embedding, memory answer, planning, Calendar execution, duplicate replay, new Calendar conflicts, changed tasks, and insert-timeout reconciliation using synthetic data and mock database/provider boundaries. TypeScript and the Next.js production build passed. See [the Indonesian implementation note](planning-hardening.md) and `evals/planning_eval.py` for repeatable checks.

**Release:** Production deployment and any live-model synthetic evaluation are recorded below after credential and release checks. No private Gmail was read and no real Calendar event was created by these tests.


### Rilis penguatan planning (2 Oktober 2026)

Commit implementasi `9598a43` sudah di-push ke `main`. API deployment `dpl_7NeNd3WkwdXM3s6UtFYAn9UA9icg` dan web deployment `dpl_5e1vh5D9XYYFD2G855nFpxxFxAnN` mencapai READY. Alias produksi tetap https://focusos-api.vercel.app dan https://focusos-web-five.vercel.app. Deployment memakai environment yang sudah tersimpan di Vercel; tidak ada environment variable baru atau migration database.

Pemeriksaan otomatis setelah deploy: `evals/hosted_smoke.py` lulus 7/7; health API dan halaman agent 200, endpoint yang membutuhkan autentikasi mengembalikan 401 tanpa sesi. OpenAPI produksi juga membuktikan `AgentRunInput.duration_minutes` opsional dan nullable. Safety gate, TypeScript, serta build lokal dan Vercel lulus.

Evaluasi Gemini live belum dijalankan: key tidak tersedia pada proses runner lokal. Review persetujuan otomatis menolak ekspor seluruh env produksi ke file lokal karena ikut menyalin kredensial yang tidak diperlukan untuk tes Gemini. Rilis tetap memakai env Vercel yang ada, tanpa mengekspor nilainya. Hasil 8/8 evaluator adalah regresi backend dengan selection sintetis, bukan pengukuran akurasi Gemini. Pengujian autentikasi produksi dengan sesi pengguna dan penulisan Google Calendar nyata tidak dilakukan; tes workflow otomatis memverifikasi keduanya pada batas integrasi yang disimulasikan.


## Produk pribadi hari 4-14 (7 Oktober 2026)

Rencana repo sebelumnya baru merinci hari 1-3; pengguna mengizinkan seluruh tahap selanjutnya dan pengujian otomatis. Scope dijabarkan pada personal-product-roadmap.md dengan fokus penggunaan pribadi dan tanpa integrasi baru.

**Hari 4-5:** Workspace task berstatus active/completed/archived, pencarian/filter project/prioritas, pagination dan edit seluruh deadline/estimasi/description/project; complete, reopen dan archive memakai optimistic version check. Library memori memperlihatkan evidence, sumber, status indexing, retry index dan removal dari retrieval. Commit workspace `367e203`; 79 tes frontend dan TypeScript lulus untuk increment itu.

**Hari 6-8:** Job queue Postgres menyimpan ID, checkpoint dan hasil ringkas; JWT sesi berada dalam tabel private sebagai ciphertext AES-GCM yang terikat ID/domain job. Sesi maksimal 15 menit, tanpa refresh token Supabase. Service-only enqueue/claim/finish memakai owner tervalidasi, SKIP LOCKED, lease 180 detik, CAS token, maksimum 64 langkah dan lima retry failure. Owned status/cancel memakai RLS. Next.js after menjalankan beberapa bounded step setelah response sehingga tab tidak menggerakkan pekerjaan baru. Planning/source di-queue sebelum response; Gmail memakai queue. Scheduler CLI dan GitHub workflow opsional menyediakan pemulihan; secret trigger belum dikonfigurasi. Cancel tidak membatalkan HTTP provider yang sudah in-flight. Halaman System menyajikan resume dan retry yang memakai sesi baru untuk source/Gmail/embedding.

**Hari 9-10:** Task manual yang diedit memperbarui source/memori, status/prioritas/estimasi/evidence/hash; vector lama dibuang dan indexing kembali pending. Gmail evidence tidak ditulis ulang. RPC creation replay setelah edit mengembalikan task terkini tanpa membuat duplikat. Schedule menampilkan action tersimpan; pembatalan event menggunakan stable ID, marker/hash, validasi konten/waktu, ETag If-Match dan sendUpdates none. Event berubah ditolak; timeout adalah unknown dan retry membaca ID sama. Task tidak ikut completed saat event cancelled. Reschedule dilakukan dengan cancel lalu plan baru.

**Hari 11-12:** Diagnostik menampilkan readiness database/migration, kehadiran konfigurasi dan nama model, tanpa nilai secret; bukan bukti quota/provider hidup. Riwayat job/run tersedia. Export data aplikasi membatasi 1000 baris per tabel dan 8 MB, memilih kolom secara eksplisit, mengabaikan seluruh credential/queue tokens/embedding, serta menyatakan truncation. Validator offline dan panduan recovery disertakan; restore database penuh belum diuji.

**Hari 13-14:** Unit, workflow, proxy, evaluator dan safety gate diperluas. Workflow worker menggunakan extraction/embedding/search/planning dan Calendar adapter dengan batas provider/database sintetis; crash setelah insert sebelum worker checkpoint tidak membuat event ganda. Migration diuji lebih dulu dalam transaksi rollback dengan user sintetis; ditemukan dan diperbaiki collision alias PL/pgSQL. Probe task memory/replay/ownership/lease/backoff/cancel credential cleanup dan cancellation/replay/foreign-user lulus. Migration 20261007090000 dan 20261007100000, serta forward fix 20261007110000 untuk serializer replay task, kemudian diterapkan pada Supabase tertaut.

Audit nama env produksi menemukan seluruh secret dasar API sudah ada; FOCUSOS_WORKER_SECRET belum ada. Evaluasi Gemini live otomatis dilewati karena key lokal tidak tersedia, tanpa mengekspor secret produksi. Tidak membaca Gmail pribadi dan tidak membuat/menghapus event Google nyata. Hasil final test/build/deployment dicatat setelah rilis selesai.

Final verification before release: 310 backend tests, 89 web tests, 7 evaluator tests and 8/8 synthetic planning regression cases passed. Expanded safety gate, TypeScript and production web build passed. Provider live evaluation remained unrun because no local Gemini key was available. The production deployment and hosted smoke are recorded below.


### Rilis produk pribadi hari 4-14

Commit `367e203` (workspace), `05292bf` (job/lifecycle/product) dan `4b3cd63` (format komponen) sudah di-push ke main. API deployment `dpl_GiwjiTsqfeWe7uvqark1icVcMbef` dan web deployment `dpl_77N3mpVUNYyFxWadRigUQxrAWhFu` mencapai READY pada alias https://focusos-api.vercel.app dan https://focusos-web-five.vercel.app. Build Vercel web memverifikasi komponen final yang sudah diformat. API mempunyai budget fungsi 180 detik; job tetap memakai lease dan batas sesi tersendiri.

Hosted smoke lama lulus 7/7; personal-product smoke lulus 13/13 (20 pemeriksaan anonim keseluruhan). Halaman tasks/schedule/system/memories 200; job/export/diagnostic/focus-block/cancel tanpa sesi 401. Scheduler tick 503 karena FOCUSOS_WORKER_SECRET belum diset, sesuai batas konfigurasi yang didokumentasikan; itu bukan bukti scheduler aktif. Supabase dry-run terakhir menyatakan migration sudah up to date. Tidak ada acceptance provider live, restore penuh atau pengujian browser login yang diklaim dari smoke anonim ini.

Daftar setup yang tersisa dan langkahnya tersedia pada remaining-work.md serta personal-product-setup.md. Tidak ada production secret yang diekspor atau event Google nyata yang diubah dalam sesi implementasi ini.


### Penyesuaian scope: tanpa backup database

Pengguna memutuskan backup database dan uji restore tidak diperlukan untuk penggunaan pribadi. Keduanya dikeluarkan dari remaining-work, roadmap dan panduan setup; bukan lagi syarat penyelesaian produk. Export aplikasi yang sudah tersedia tetap opsional. Tidak ada perubahan kode, database atau konfigurasi produksi.
