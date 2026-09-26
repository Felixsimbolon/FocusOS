# FocusOS Implementation Log

Last updated: 2026-09-26

This log records what was implemented and why, one increment at a time. The detailed product scope, acceptance criteria, architecture tradeoffs, and future increments remain in [plan.md](../plan.md).

## Current state

The chosen application shape is a Next.js web UI with a Python/FastAPI API (D1, Option B). Supabase Auth with Google sign-in is the selected application identity path (D2, Option A). Supabase client access with versioned SQL migrations is selected for persistence (D3, Option A). Code is in place through Increment 1.8. Google sign-in/sign-out, database identity, and profile save/read were verified against the linked Supabase project. The profile isolation check used a synthetic second identity in a rolled-back database transaction. Increments 1.1–1.8 are verified; Phase 1 is complete. The hosted web and API run on two Vercel Hobby projects. Phase 2 began after D4 was selected. Increments 2.1 and 2.2 are complete. D13 Option A (incremental consent and owned primary Calendar) is selected. Increment 2.3 code is implemented with live consent setup pending; 2.4 implementation, production build, and SQL grants are verified; live OAuth verification is pending. Increment 2.5 code and mocked tests are implemented; reading a live synthetic email remains pending.

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
