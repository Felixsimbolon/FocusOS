# FocusOS Implementation Log

Last updated: 2026-09-26

This log records what was implemented and why, one increment at a time. The detailed product scope, acceptance criteria, architecture tradeoffs, and future increments remain in [plan.md](../plan.md).

## Current state

The chosen application shape is a Next.js web UI with a Python/FastAPI API (D1, Option B). Supabase Auth with Google sign-in is the selected application identity path (D2, Option A). Supabase client access with versioned SQL migrations is selected for persistence (D3, Option A). Code is in place through Increment 1.7. Google sign-in/sign-out, database identity, and profile save/read were verified against the linked Supabase project. The profile isolation check used a synthetic second identity in a rolled-back database transaction. Increment 1.7 is verified locally; Increment 1.8 is next.

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

## How this log will be maintained

After each future increment, append a dated section with the increment number, purpose, files changed, what was added and why, commands/tests and their results, manual verification, known limitations, and the next gated increment. Keep incomplete live checks explicitly marked as pending. Do not mark plan checklist items complete unless their stated acceptance checks actually passed.
