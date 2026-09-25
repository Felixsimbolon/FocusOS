# FocusOS

FocusOS is a personal AI productivity agent. Its implementation plan is in [plan.md](plan.md), and the step-by-step build history is in [docs/implementation-log.md](docs/implementation-log.md). The project has a Next.js web app and a small Python API.

## Run locally

Use Node.js 20.9 or newer and Python 3.10 or newer.

Install the web app dependencies from the repository root:

```powershell
npm.cmd install --prefix web
```

Create the project-local Python environment and install the API package:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\backend
```

In separate terminals, start the web app and API:

```powershell
npm.cmd run dev:web
```

```powershell
npm.cmd run dev:api
```

The web app is at http://localhost:3000. The API health endpoint is at http://127.0.0.1:8000/health.

## Configure Google sign-in

Create a Supabase project and enable Google under **Authentication → Providers**. In Google Cloud, set Supabase's callback URL as an authorized redirect URI. In Supabase's URL configuration, add `http://localhost:3000/auth/callback` to the allowed redirect URLs.

Copy the values in [`.env.example`](.env.example) into `web/.env.local`. Set `FOCUSOS_APP_URL=http://localhost:3000` for local development; set it to the deployed web app origin in production. Then start the web app. The login callback uses PKCE; application sessions contain Supabase session tokens only, and the app does not request Gmail or Calendar scopes yet.

Use only the project URL and publishable key here. Never put a Supabase service-role key or Google client secret in `web/.env.local` or browser code.

See Supabase's [Google sign-in guide](https://supabase.com/docs/guides/auth/social-login/auth-google) and [Next.js SSR setup](https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs&package-manager=npm&queryGroups=framework&queryGroups=package-manager) for the provider setup details.

Run the focused web checks with:

```powershell
npm.cmd run test:web
```

