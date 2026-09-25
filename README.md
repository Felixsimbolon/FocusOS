# FocusOS

FocusOS is a personal AI productivity agent. Its implementation plan is in [plan.md](plan.md). The project has a Next.js web app and a small Python API.

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
python -m pip install -e ./backend
npm.cmd run dev:api
```

The web app is at http://localhost:3000. The API health endpoint is at http://127.0.0.1:8000/health.

