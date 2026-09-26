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
