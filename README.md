# FocusOS

FocusOS is a personal AI productivity agent. Its implementation plan is in [plan.md](plan.md), and the step-by-step build history is in [docs/implementation-log.md](docs/implementation-log.md). The project has a Next.js web app and a Python/FastAPI API.

## Run locally

Use Node.js 20.9 or newer and Python 3.10 or newer. From the repository root, install the project-local Supabase CLI, web dependencies, and API package:

```powershell
npm.cmd install
npm.cmd install --prefix web
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\backend
```

Create a Supabase project and enable Google under **Authentication -> Providers**. In Google Cloud, set Supabase's callback URL as an authorized redirect URI. In Supabase's URL configuration, add `http://localhost:3000/auth/callback` to the allowed redirect URLs. Use the same Supabase project URL and `sb_publishable_...` key for both runtimes. The backend rejects a secret/service-role key. Copy [`.env.example`](.env.example) to `web/.env.local`, then replace the placeholders. `FOCUSOS_APP_URL` is the web origin; `FOCUSOS_API_URL` is the FastAPI origin. Never put a Google client secret or Supabase secret/service-role key in `web/.env.local` or browser code.

In one terminal, set the FastAPI variables and start the API:

```powershell
$env:FOCUSOS_SUPABASE_URL = "https://your-project.supabase.co"
$env:FOCUSOS_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_your-project-key"
npm.cmd run dev:api
```

In a second terminal, start the web app:

```powershell
npm.cmd run dev:web
```

The web app is at http://localhost:3000. The open API health endpoint is at http://127.0.0.1:8000/health. The login callback uses PKCE; application sessions contain Supabase session tokens only. Gmail and Calendar scopes are not requested yet. See Supabase's [Google sign-in guide](https://supabase.com/docs/guides/auth/social-login/auth-google) and [Next.js SSR setup](https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs&package-manager=npm&queryGroups=framework&queryGroups=package-manager) for provider setup details.

## Database migration and identity check

The project-local Supabase CLI owns ordered SQL migrations in `supabase/migrations/`. Once your Supabase project exists, link it and apply pending migrations:

```powershell
npm.cmd exec -- supabase login
npm.cmd exec -- supabase link --project-ref YOUR_PROJECT_REF
npm.cmd run db:push
```

`db:push` writes the pending SQL migration to the linked project. The first migration creates a read-only `focusos_session_uid()` probe for authenticated users. The second creates owned profiles for timezone and working hours, with row-level security and limited column grants. The backend verifies the bearer token with Supabase Auth, sends that same token to PostgREST, and checks that the database sees the same user ID. It creates a fresh client per request. [Supabase CLI migration workflow](https://supabase.com/docs/guides/local-development/cli-workflows) and [Python client setup](https://supabase.com/docs/reference/python/initializing) provide the underlying commands and client details.

After signing in at http://localhost:3000, open http://localhost:3000/api/db-check. Expect `{"status":"ok"}`. After signing out, expect HTTP 401. Calling `http://127.0.0.1:8000/health/database` without a bearer token also returns 401. The browser never needs to send a token directly to FastAPI; the Next.js route forwards it server-side. If the migration or backend configuration is missing, the signed-in check returns 503.

Run focused local checks with:

```powershell
npm.cmd run test:web
npm.cmd run test:api
npm.cmd run build:web
```

The automated API tests use mocks. The project has also been checked against a linked Supabase project: Google sign-in and sign-out, identity propagation, profile save/read, anonymous denial, and an RLS check using a second synthetic identity. Run those live checks against your own project after applying migrations.

## Scheduling preferences

After signing in, open http://localhost:3000/settings, review the suggested timezone and working days/hours, and save. Reload the page to see the stored values. The Next.js server sends the session access token to FastAPI, which validates the values and queries Supabase as that user. The browser form and profile responses do not expose the token or the server-controlled allowlist flag. An anonymous visit to /settings returns to the home page.
