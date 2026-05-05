# Getting Started

AI DevFlow Engine runs as a local backend API plus a Vite frontend workspace. Backend commands use the repository-local `uv` environment. Frontend and E2E commands use their own `npm --prefix` package roots.

## Prerequisites

| Tool | Required version |
| --- | --- |
| Python | `3.11` or newer |
| uv | Used for backend dependency sync and Python commands |
| Node.js | `^20.19.0` or `>=22.12.0` |
| npm | Bundled with the selected Node.js runtime |

Do not install Python packages globally for this project. Backend dependencies belong in `pyproject.toml` and `uv.lock`; frontend dependencies belong under `frontend/`; E2E dependencies belong under `e2e/`.

## Backend Setup

Install backend dependencies:

```powershell
uv sync --extra dev
```

Start the API:

```powershell
uv run uvicorn backend.app.main:app --reload
```

The API starts on `http://127.0.0.1:8000` by default. OpenAPI documentation is available at:

```text
http://127.0.0.1:8000/api/docs
```

Runtime data defaults to `.runtime/` under the current working directory. Override it with `AI_DEVFLOW_PLATFORM_RUNTIME_ROOT` when a different local runtime directory is required.

## Frontend Setup

Install frontend dependencies:

```powershell
npm --prefix frontend install
```

Start the frontend against the local backend:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000/api"
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open the workspace at:

```text
http://127.0.0.1:5173
```

## E2E Setup

Install E2E dependencies:

```powershell
npm --prefix e2e install
```

Run Playwright against the mocked frontend flow:

```powershell
npm --prefix e2e run test
```

Run Playwright with the live backend harness:

```powershell
npm --prefix e2e run test:live
```

The live backend harness starts a backend server through `uv run --no-sync python e2e/support/live-backend-server.py` and starts the frontend dev server with the matching API base URL.

## Useful Environment Variables

| Variable | Purpose |
| --- | --- |
| `AI_DEVFLOW_PLATFORM_RUNTIME_ROOT` | Runtime data root for SQLite files, workspaces, and logs. |
| `AI_DEVFLOW_DEFAULT_PROJECT_ROOT` | Default project root seeded by the backend. |
| `AI_DEVFLOW_WORKSPACE_ROOT` | Workspace root override. |
| `AI_DEVFLOW_BACKEND_CORS_ORIGINS` | Allowed frontend origins for backend CORS. |
| `VITE_API_BASE_URL` | Frontend API base URL, usually `http://127.0.0.1:8000/api` during local development. |
| `E2E_LIVE_BACKEND` | Set to `1` to run Playwright with the live backend harness. |
| `E2E_FRONTEND_PORT` | Frontend port for E2E runs. Defaults to `5173`. |
| `E2E_BACKEND_PORT` | Backend port for live E2E runs. Defaults to `8000`. |
