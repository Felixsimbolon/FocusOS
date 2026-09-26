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

Phase 5 deployments are READY: API `dpl_7WCoo4LbtZ1Y1tCgL57J6kkcajz6` and web `dpl_9dDTw1iwzSEYAR5xwAjF2kGu2cZD`, both on the stable aliases above. Anonymous smoke checks returned API health 200, web Activity 200, and Gmail status/sync/process routes 401. The Vercel environment-name audit shows the web project still lacks `FOCUSOS_GOOGLE_CLIENT_ID` and `FOCUSOS_GOOGLE_STATE_SECRET`, while the API lacks the OAuth client credentials, redirect allowlist, token keyring, service-role key, and OpenAI key. Thus the live provider journey remains unverified until these private values are configured and both projects redeployed. The code and database migrations are deployed; do not interpret READY as completed Gmail consent or extraction acceptance.

## Phase 6 Calendar availability (2026-09-27)

No new account is needed. Use the existing Google Cloud project with Google Calendar API enabled, the same OAuth Web client and Calendar read consent from Phase 2, and saved timezone/working hours in FocusOS. Production still needs the Google OAuth/client and encrypted-token secrets documented in the Phase 5 setup section; these names were absent in the latest Vercel environment audit. Add them privately, redeploy API and web as needed, then connect Google at `/settings/connections`.

Open Today and choose **Check availability** for Today or the next seven local days. With a synthetic busy event on the primary Calendar, confirm it appears in the schedule and no suggested free slot overlaps. Check an all-day/recurring event and a deliberately oversized duration: shortfall must be visible. Disconnect or revoke Calendar consent and confirm the UI reports unavailability, never “all day free.” The preview is read-only and must be refreshed before any future event write. Do not copy personal event titles, credentials, or cookies into reports.

The backend rejects a Calendar window after any missing/failed page, a repeated pagination cursor, more than five pages/500 events, invalid timezone, or ambiguous DST boundary. Live provider comparison remains pending until the existing Google integration secrets are configured; a green deployment alone does not establish real Calendar acceptance.

Phase 6 production deploys reached READY on 2026-09-27: API `dpl_EiVrDfB5Be6aztCYcxCTHtbeiyGh`, web `dpl_3NTeTRy8nyKWSCZoDXdSn7v4caT6`. Smoke checks: API `/health` 200, web Today 200, and anonymous Calendar window/availability API plus web proxy 401. Backend 160 tests, web 46 tests, and the production web build passed. The live Calendar comparison remains pending the same private OAuth/token configuration described above; no real provider event was read in this verification.

## Phase 7: agen perencanaan (2026-09-27)

Tidak perlu akun baru. Gunakan project Supabase, Google Cloud OAuth/Calendar, OpenAI Platform, dan dua project Vercel yang sudah ada. Migration Supabase Phase 7 untuk `command_runs`, ledger tool, memori terkonfirmasi, embedding pgvector 256 dimensi, dan pencarian sudah diterapkan. Jalankan `npm.cmd run db:push` bila menyiapkan database baru.

Sebelum uji end-to-end, isi variabel privat berikut di **Vercel project API**: `FOCUSOS_OPENAI_API_KEY` (ekstraksi, embedding, dan perencanaan Responses); `FOCUSOS_SUPABASE_SERVICE_ROLE_KEY` (akses server untuk token Google terenkripsi); `FOCUSOS_TOKEN_ENCRYPTION_KEYS` dan `FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION` (enkripsi/dekripsi token Google); `FOCUSOS_GOOGLE_CLIENT_ID`, `FOCUSOS_GOOGLE_CLIENT_SECRET`, dan `FOCUSOS_GOOGLE_REDIRECT_URIS` (pertukaran/refresh OAuth serta allowlist callback). Format dan alasan detail ada di `backend/.env.example` dan bagian Phase 5 di atas. **Vercel project web** membutuhkan `FOCUSOS_GOOGLE_CLIENT_ID` dan `FOCUSOS_GOOGLE_STATE_SECRET` agar alur connect Google aman. Semua ini hanya server-side. Pastikan Google Calendar API aktif dan consent read Calendar diberikan. Setelah menambah variabel, deploy ulang API dan web. Jangan kirim nilai rahasia melalui chat atau commit.

Buka `/agent` setelah login. Coba perintah sintetis dengan task yang memiliki tenggat waktu, event Calendar sibuk, dan durasi 60 menit; lanjutkan satu tahap per klik sampai hasil muncul, lalu reload `/agent/{runId}`. Pastikan jumlah task/event/memori dan empat tool baca terlihat. Coba deadline date-only, durasi yang tak muat, dan Calendar terputus: hasil harus berupa pertanyaan, shortfall, atau error aman; tidak boleh membuat event Calendar. Untuk memori, konfirmasi fakta berbukti di `/activity`, klik embed, lalu jalankan perintah relevan; bila embedding gagal, mode pencarian harus jelas sebagai lexical fallback.

Deploy produksi Phase 7 READY: API `dpl_YefXM6YF9KBUneRzzjHffojMFL3Q`, web `dpl_52wdPVvCWgGeqePyWjLbHAQ7hkoD`; alias tetap https://focusos-api.vercel.app dan https://focusos-web-five.vercel.app. Smoke test anonim: `/health` 200, `/agent` 200, tiga route run tanpa sesi 401. Audit nama environment menunjukkan variabel privat di atas belum ada pada kedua project, sehingga uji provider nyata belum dapat dinyatakan lulus. Git push tidak memicu deploy otomatis pada project ini; perintah deploy CLI ada di awal dokumen.
