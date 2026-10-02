# Notebook Factory

A public library of Python notebooks, with a focused JupyterLab editor available only to GitHub user **1st1**.

- React sidebar, search, notebook creation, rendered cells and outputs, and `.ipynb` downloads.
- GitHub OAuth with signed, expiring HttpOnly cookies and server-side owner/origin checks.
- JupyterLab in Vercel Sandbox, provisioned exclusively through the **Python Sandbox SDK**.
- Private drafts autosave every 30 seconds. **Publish** updates the public notebook; **Close editor** saves and stops the sandbox.
- Postgres persistence on Vercel; SQLite for local development. Sandbox files and kernels are temporary. Only the notebook document and its outputs are restored when a new sandbox starts.

## Run locally

Requires Python 3.12+, Node 20.19+ (or 22.12+), and uv.

```sh
cp backend/.env.example backend/.env
uv sync --project backend
npm ci --prefix frontend
```

Create a GitHub OAuth App with homepage `http://localhost:5173` and callback `http://localhost:5173/api/auth/callback`. Put its client ID and secret in `backend/.env`. Set a random `SESSION_SECRET` (for example, `openssl rand -hex 32`). There is no development authentication bypass.

Run these in separate terminals:

```sh
cd backend
uv run uvicorn main:app --reload --port 8000
```

```sh
npm run dev --prefix frontend
```

Open `http://localhost:5173`. The empty workspace and public viewing work without GitHub credentials; signing in requires the OAuth configuration. Vite proxies `/api` to FastAPI.

Alternatively, run both services behind the Vercel local gateway:

```sh
APP_URL=http://localhost:3000 VERCEL_ENV=development npx vercel@latest dev -L
```

For that mode, register `http://localhost:3000/api/auth/callback` in your local GitHub OAuth app. The current published CLI is needed; older custom builds may reject service rewrite objects.

For local Sandbox access, use a linked Vercel project's OIDC token or set `VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, and `VERCEL_TEAM_ID` in `backend/.env`. These belong to the backend only. Never put credentials in `VITE_*` variables.

## Deploy to Vercel

The root `vercel.json` defines two [Vercel Services](https://vercel.com/docs/services): `web` (Vite) and `api` (FastAPI). Top-level rewrites send `/api/*` to FastAPI and other paths to the frontend. Jupyter's HTTP and WebSocket traffic goes directly to its Sandbox URL, avoiding a WebSocket proxy through a Function.

1. Import this directory as the project root, or run `vercel link` from it. Use Vercel CLI 62.1.0 or newer (the Services setup was verified with 62.1.0).
2. Connect a Postgres database (for example Neon through Vercel Marketplace). Set `DATABASE_URL` to its connection URL, including TLS options. Tables are initialized automatically with a Postgres advisory lock protecting concurrent cold starts.
3. Set `APP_URL` to the canonical HTTPS origin, `SESSION_SECRET` to a cryptographically random value of at least 32 characters, and `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` to your GitHub OAuth App credentials. Register `${APP_URL}/api/auth/callback` as the OAuth callback. Use a separate OAuth app/origin for preview environments if editing there is needed.
4. Enable the project's Vercel OIDC token support and Sandbox access. The Python SDK uses the request-scoped token; a static Vercel token is unnecessary in production.
5. Deploy with `vercel --prod`. The API function has a 300-second startup budget. Verify `/api/health`, sign in as `1st1`, create a notebook, edit/run a cell, publish, and view it signed out.

The frontend never receives database credentials or GitHub access tokens. Anyone can read **published** notebooks, so do not publish secret outputs. The editor URL is an unguessable, per-session capability and is returned only after owner authorization. Treat it like a password. Closing an editor stops that capability's server; signed-out readers never get an editor URL. Logout is disabled while editing; close the editor first.

## Editing lifecycle

First startup installs Python 3.13 and pinned JupyterLab 4.4.10 in a Sandbox virtual environment. The embedded layout and template bridge were adapted from `vercel-py` branch `nb_next`, commit `8296336`. Their original MIT license is in `backend/assets/LICENSE`.

The bridge checks the parent origin, message source, and session capability, then awaits Jupyter's document save API. The backend reads and validates `notebook.ipynb` before storing it. Rendering uses nbconvert without executing code and is isolated by both iframe sandboxing and a response CSP.

A database lease serializes editor operations across function instances. Existing live editors are reused. A closed or expired sandbox is recreated from the durable draft. The sandbox starts with a 15-minute limit; active draft saves extend it by 30 seconds. Closing the browser stops heartbeats, allowing the sandbox to expire. Up to the last 30 seconds of changes can be lost if the browser or sandbox disappears before the next durable save. Uploaded files, extra installed dependencies, and kernel memory are not persisted.

The notebook size limit is 10 MB. Advanced interactive outputs requiring external API calls or nested frames are restricted by the public renderer's CSP. Notebook titles are set at creation; the scope does not include deletion or collaborative editing.

## Checks

```sh
uv run --project backend pytest backend/tests -q
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
npm run build --prefix frontend
lat check
```

The backend tests use a temporary SQLite database and mocked Sandbox operations. They cover authorization, OAuth state rejection, draft/public separation, stale editor tokens, persistence after close, sandbox startup failures, expired editor recovery, concurrent startup serialization, and validation failures that must not stop the editor. Browser smoke checks also verified public/owner views and mobile navigation; a real local JupyterLab check verified cell execution and the save bridge. Live OAuth, Postgres, and Sandbox verification require provisioned credentials.
