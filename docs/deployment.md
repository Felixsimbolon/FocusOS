# Early deployment probe

Increment 1.8 deploys the current identity/profile slice as **two Vercel projects** from this repository: `web/` (Next.js) and `backend/` (FastAPI). Choose the Hobby plan only for a personal, noncommercial portfolio demo. The Python runtime is still beta. The deployed API runs as a bounded function; no background worker is assumed.

## Create the projects

1. In Vercel, import `Felixsimbolon/FocusOS` twice. Name the projects `focusos-web` and `focusos-api` (or use unique names available to your account).
2. Set the first project's **Root Directory** to `web` and framework to **Next.js**. Set the second project's **Root Directory** to `backend`; Vercel uses the explicit `backend/vercel.json` FastAPI preset and the ASGI app at `src/index.py`. The backend pins Python 3.12 in `backend/.python-version`. The web preset is pinned in `web/vercel.json`.
3. Set the API project's Production environment variables: `FOCUSOS_SUPABASE_URL` and `FOCUSOS_SUPABASE_PUBLISHABLE_KEY`, copied from the same Supabase project as local development. Use only the publishable key, never the service-role key.
4. Deploy the API and record its stable production URL. Check `/health` returns `{"status":"ok"}`, while `/profile` without a bearer token returns 401.
5. Set the web project's Production environment variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `FOCUSOS_API_URL` (the API production origin), and `FOCUSOS_APP_URL` (the web production origin). Do not add a trailing route path. Redeploy the web project after setting these values.
6. In Supabase Authentication → URL Configuration, add `https://YOUR_WEB_DOMAIN/auth/callback` to **Redirect URLs** and set the Site URL to the stable web origin if it is the intended default. The Google Cloud OAuth redirect remains Supabase's own callback URL; the Vercel URL is added in Supabase's allowlist.


## Current project URLs (2026-09-26)

- Web: https://focusos-web-five.vercel.app
- API: https://focusos-api.vercel.app

These projects were created and deployed through the Vercel CLI. The Production environment values are configured on the two projects. The connected Vercel team reports the Hobby plan; Vercel Python is a beta runtime. CLI deployments use the linked local `web/` and `backend/` directories:

```powershell
npm.cmd exec --yes --package=vercel -- vercel deploy --prod --cwd backend
npm.cmd exec --yes --package=vercel -- vercel deploy --prod --cwd web
```

Git-triggered deployments are not configured yet. A Git push alone does not update these hosted projects; connect the repository and set each project's Root Directory in Vercel before relying on automatic deploys. The active Supabase Redirect URLs include `https://focusos-web-five.vercel.app/auth/callback`. Hosted login, profile persistence after reload, and sign-out were verified on 2026-09-26.

## Verify the hosted slice

Open the stable web URL in a private browser window. Confirm the root loads and `/api/me` returns 401 before login. Sign in with Google, then open `/api/me`: it should return `user` and `profile` without any token or internal allowlist flag. Save timezone and working hours at `/settings`, reload, and verify persistence. Sign out and confirm `/api/me` returns 401 again. Record the final URLs and date in `docs/implementation-log.md`. Do not paste tokens, cookies, keys, or user IDs into the log.

If the API function cold-starts slowly, retry the first request once; repeated failures require inspecting Vercel deployment logs and checking `FOCUSOS_API_URL` and both Supabase environment variables. The Next.js server calls FastAPI directly, so browser CORS configuration is not required for this slice.

References: [Vercel monorepos](https://vercel.com/docs/monorepos), [FastAPI on Vercel](https://vercel.com/kb/guide/ship-a-fastapi-app-on-vercel), [Python runtime](https://vercel.com/docs/functions/runtimes/python), [Hobby plan](https://vercel.com/docs/plans/hobby).

## Phase 3 production deploy (2026-09-27)

Phase 3 code is deployed to the existing production aliases:

- Web: https://focusos-web-five.vercel.app (deployment dpl_ECAbJU3wn7mmfMzFaTr6bGfagSWr)
- API: https://focusos-api.vercel.app (deployment dpl_27TqkKascunbXfjVV8RMMbTCVFLj)

Both deployments reached READY. Smoke checks: API /health returned 200; anonymous /api/me, /api/tasks/today, /api/projects, and POST /api/tasks returned 401. The anonymous task POST created no data. No user token or cookie was used during these checks.

To verify the signed-in lifecycle, open the web URL, sign in with Google, create a task, reload and confirm it remains, edit its title, and mark it complete. The Today list removes completed tasks. The implementation uses the profile timezone, or UTC if no profile exists. Live Google provider consent/read acceptance from Phase 2 remains pending.

## Phase 4 production deploy (2026-09-27)

Phase 4 API and web deployments reached READY on the existing aliases:

- API: https://focusos-api.vercel.app (deployment dpl_EsfyXwA2qYj8yP4TVeEx4JnPYH2g)
- Web: https://focusos-web-five.vercel.app (deployment dpl_EKfqC3R6iPMJ2HFfJCh64zWrwgnR)

Applied Supabase migrations 20260927010000 through 20260927050000. Production checks returned API `/health` 200 and web `/activity` 200. Anonymous `/api/sources`, source extraction reads, and POST confirmation returned 401.

To activate model extraction, create an OpenAI Platform API key with available API usage. Add **FOCUSOS_OPENAI_API_KEY** as a Production secret to the `focusos-api` Vercel project, then redeploy the API. For local development, set it only in the backend process environment; do not put it in `web/.env.local`, a `NEXT_PUBLIC_` variable, Git, or browser code. No OpenAI key was present during this deployment, so the live provider call has not been verified. The current API responds with a safe failed extraction record (`provider_unconfigured`) while the key is absent.

After adding the key, sign in at the web URL, open `/activity`, paste a synthetic message such as `Presentation Friday 25 September 2026. Submit slides one day before.`, save, extract, review the exact quote and Thursday date, then confirm. Open Today and follow the source link on the saved task. Also try an ambiguous phrase such as `next Friday` and check that no deadline is silently invented. Never paste a key, access token, cookie, or private email into diagnostics.

## Phase 5 Gmail setup and acceptance (2026-09-27)

No additional account is required if the existing Google Cloud, Supabase, Vercel, and OpenAI Platform accounts are available. The Gmail feature is selected-label only: in Gmail create a user label named exactly `FocusOS`, apply it to a small set of test messages, and enable Gmail API in the same Google Cloud project used for FocusOS OAuth. The Google OAuth Web client must allow `https://focusos-web-five.vercel.app/api/integrations/google/callback` as an authorized redirect URI. In Google Auth Platform, keep the OAuth app in External testing with the account added as a test user, or complete the provider's production verification requirements for wider use. Add the `gmail.readonly` scope to the consent configuration. That scope is restricted; broad public rollout requires Google verification and may require a security assessment.

The **web Vercel project** needs `FOCUSOS_GOOGLE_CLIENT_ID` for the authorization URL and `FOCUSOS_GOOGLE_STATE_SECRET` for CSRF/state protection, in addition to the existing Supabase/app/API variables. Neither is a `NEXT_PUBLIC_` browser variable. The **API Vercel project** needs `FOCUSOS_SUPABASE_SERVICE_ROLE_KEY` to manage the private encrypted-token table; `FOCUSOS_TOKEN_ENCRYPTION_KEYS` and `FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION` to encrypt/decrypt Google refresh tokens; `FOCUSOS_GOOGLE_CLIENT_ID` and `FOCUSOS_GOOGLE_CLIENT_SECRET` to exchange and refresh OAuth tokens; and `FOCUSOS_GOOGLE_REDIRECT_URIS` to allow only the exact local/production callback addresses. `FOCUSOS_OPENAI_API_KEY` is needed for the Phase 4 extraction handoff after Gmail ingest. Use `backend/.env.example` and the root README for exact formats. Store values only in Vercel Production secrets or ignored local environment files; do not send them in chat, commit them, or put them in browser variables.

After adding or changing Production variables, redeploy the affected project(s). Sign in to FocusOS, open `/settings/connections`, connect Google with Gmail read access, and open `/activity`. Click **Sync Now**, then **Continue sync** while partial pages remain. The panel displays saved/ready/pending/failed counts and retry time. Click **Process one source** for each pending source and review candidates below before confirming a task. Close/reopen the page mid-sync and verify it resumes. Repeat Sync Now with unchanged messages and verify no duplicate source. Remove a label from a test message before syncing and verify it is not imported. The demo has no scheduled background sync; changes appear only after another manual trigger. Never share emails, tokens, cookies, or keys in test reports.

Google provider references: [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [OAuth test users](https://support.google.com/cloud/answer/15549945), [Gmail sync history](https://developers.google.com/workspace/gmail/api/guides/sync).
