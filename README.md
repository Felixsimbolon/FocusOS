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

The web app is at http://localhost:3000. The open API health endpoint is at http://127.0.0.1:8000/health. The login callback uses PKCE; application sessions contain Supabase session tokens only. The Supabase sign-in callback does not request Gmail or Calendar access; a separate server-side OAuth flow handles those permissions. See Supabase's [Google sign-in guide](https://supabase.com/docs/guides/auth/social-login/auth-google) and [Next.js SSR setup](https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs&package-manager=npm&queryGroups=framework&queryGroups=package-manager) for provider setup details.

## Google OAuth consent setup (Phase 2)

The separate Google integration consent flow returns to Next.js; it does not use Supabase's Auth callback. In Google Cloud, use the same OAuth Web application client if desired and add these exact Authorized redirect URIs:

- http://localhost:3000/api/integrations/google/callback
- https://focusos-web-five.vercel.app/api/integrations/google/callback

Enable the Gmail API and Google Calendar API in that project and add the account you will test with to the OAuth audience's test users. The first consent requests openid/email/profile, Gmail read-only, and read-only events on calendars you own. A separate button requests the owned-calendar event-write scope only when the user chooses to enable it; that consent flow does not create or change events. Google defines this scope as allowing users to see, create, change, and delete events on calendars they own ([scope details](https://developers.google.com/workspace/calendar/api/auth)); FocusOS will require approval for event writes and will not expose event deletion. The current probe assumes the primary Calendar ID, so it does not request permission to list every calendar. Google classifies gmail.readonly as a restricted scope; this phase is a controlled test-user integration, not public verified onboarding.

Set FOCUSOS_GOOGLE_CLIENT_ID and FOCUSOS_GOOGLE_STATE_SECRET in web/.env.local. The client ID is not a secret; the state secret must be a separately generated 32-byte Base64 key and stays server-side. Generate one with .\.venv\Scripts\python.exe -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())". Do not reuse the AES encryption key as the state-protection key. Keep the Google client secret in the FastAPI environment only.

## Server-only Google token configuration (Phase 2)

Increment 2.2 adds server-side token protection and refresh primitives. Increment 2.4 exchanges the Google code in FastAPI and stores only encrypted tokens. Never put the Supabase service-role key, AES encryption keyring, or Google client secret in web/.env.local, any NEXT_PUBLIC_ variable, or Git. The Google client ID and a separate state-protection key are server-only web settings described above.

For the FastAPI process only, prepare these variables when continuing to the Google connection setup. A placeholder template is in `backend/.env.example`; set real values in the API process environment, never in `web/.env.local`.

- FOCUSOS_SUPABASE_SERVICE_ROLE_KEY: the Supabase secret/service-role key. It is used only for database RPCs that are explicitly granted to service_role; ordinary profile and connection reads still use the signed-in user's token.
- FOCUSOS_TOKEN_ENCRYPTION_KEYS: a JSON object mapping key versions to Base64-encoded 32-byte AES keys, such as {"1":"<base64-key>"}.
- FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION: the version used for new ciphertext, initially 1. Keep older keys in the keyring until all ciphertext using them has been re-encrypted.
- FOCUSOS_GOOGLE_CLIENT_ID and FOCUSOS_GOOGLE_CLIENT_SECRET: the OAuth web-client credentials held by FastAPI for code exchange and refresh.
- FOCUSOS_GOOGLE_REDIRECT_URIS: comma-separated exact allowlist of the local and hosted Next.js callback URLs; FastAPI rejects any other redirect URI.

Generate a key locally with .\.venv\Scripts\python.exe -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())". Store the result and all other secret values in the FastAPI environment or the API host's private environment settings. The encryption helper fails closed if its keyring is malformed or lacks the active key. Losing the only key that can decrypt saved tokens requires users to reconnect.



After Google is connected, the Connections page can read a bounded page from the primary Calendar for the next seven days. Calendar titles and details are not displayed or saved. The write-scope upgrade can be verified from the same page without creating or changing an event.

The Connections page can also probe one synthetic test email. Obtain its message ID with Gmail's [`users.messages.list` API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), then enter that ID. The probe uses `users.messages.get` with `format=full` on the server, computes a body byte count in memory, and returns only the message ID/date/label count/body size. It does not persist or return the message body. Use only a test email for this probe.

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

## Protected identity route

While signed in, open http://localhost:3000/api/me to inspect the small identity/profile JSON used by the home page. It contains only user.id, user.email, and saved timezone/working hours (or profile: null before saving). Anonymous requests return HTTP 401; an unavailable profile backend returns HTTP 503. The route always sets Cache-Control: no-store and never returns an access token, cookie, or allowlist flag.

For the two-project Vercel deployment probe, follow [docs/deployment.md](docs/deployment.md).
