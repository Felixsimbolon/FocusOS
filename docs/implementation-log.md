# FocusOS Implementation Log

Last updated: 2026-09-25

This log records what was implemented and why, one increment at a time. The detailed product scope, acceptance criteria, architecture tradeoffs, and future increments remain in [plan.md](../plan.md).

## Current state

The chosen application shape is a Next.js web UI with a Python/FastAPI API (D1, Option B). Supabase Auth with Google sign-in is the selected application identity path (D2, Option A). The implementation code is in place through Increment 1.4. The real Google login smoke check is still pending Supabase and Google provider configuration. The next planned work is Increment 1.5, after choosing D3 for database access.

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

**Choice:** Option A, selected by the user: Supabase Auth manages the application session and Google is the sign-in provider. D3 and later choices remain open.

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

**Manual verification still needed:** Create/configure a Supabase project and Google provider, set the values from `.env.example` in `web/.env.local`, add `http://localhost:3000/auth/callback` to Supabase's allowed redirects, run `npm.cmd run dev:web`, then complete Google sign-in and sign-out. No live OAuth credentials were available during implementation, so the login round trip has not been claimed as tested.

**Current boundary:** FastAPI still exposes only its initial health route; protected API identity propagation is later work. Gmail and Calendar scopes, Google token storage, and database access are also not implemented here.

## How this log will be maintained

After each future increment, append a dated section with the increment number, purpose, files changed, what was added and why, commands/tests and their results, manual verification, known limitations, and the next gated increment. Keep incomplete live checks explicitly marked as pending. Do not mark plan checklist items complete unless their stated acceptance checks actually passed.
