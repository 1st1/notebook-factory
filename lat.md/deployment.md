# Deployment and operation

The app deploys from the repository root as two Vercel Services, with Neon Postgres for persistence and Vercel Sandbox for notebook execution.

## Production project

The configured production application is [notebook-factory-green.vercel.app](https://notebook-factory-green.vercel.app), under the Vercel team `yury-selivanovs-projects`.

| Setting | Project value |
| --- | --- |
| Git repository | `https://github.com/1st1/notebook-factory` |
| Local Git remote | `up` |
| Vercel project | `notebook-factory` |
| Project ID | `prj_6Q4NWdJ0w3VHaXshi9MoWKwhdPhP` |
| Team ID | `team_7scPglQEOz4JjqD4f08fLr7z` |
| Database | Connected Neon Marketplace integration |
| Application owner | GitHub login `1st1` |

These are the project details verified during setup on October 1, 2026. Local linkage lives in the ignored `.vercel/project.json`. Production has been deployed directly from the working tree with the CLI; a successful deployment does not imply those changes have been committed or pushed.

The production alias is public. Unique deployment URLs have Vercel deployment protection, so use the canonical alias for public checks and OAuth. See [[architecture#Services]] for routing and function configuration.

## Environment configuration

[[backend/config.py]] validates deployment settings, and [backend/.env.example](../backend/.env.example) lists backend variables. Secrets belong in Vercel environment settings or ignored local environment files.

| Variable | Purpose |
| --- | --- |
| `AI_MODEL` | Optional chat model; defaults to gateway:openai/gpt-6-luna |
| `AI_GATEWAY_API_KEY` | Optional AI Gateway key; deployments use Vercel OIDC by default |
| `APP_URL` | Canonical app origin; production uses `https://notebook-factory-green.vercel.app` |
| `BLOB_READ_WRITE_TOKEN` | Backend upload credential for the public rendered-notebook Blob store |
| `SESSION_SECRET` | Random signing secret, at least 32 characters in deployment |
| `DATABASE_URL` | Neon/Postgres connection URL with TLS options |
| `GITHUB_CLIENT_ID` | OAuth application client ID |
| `GITHUB_CLIENT_SECRET` | OAuth application secret |
| `VERCEL_OIDC_TOKEN` | Request-scoped Sandbox identity in deployment, or an explicitly loaded local token |
| `VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID` | Alternative backend-only Sandbox credentials for local use |

The production GitHub OAuth homepage is the canonical app origin; its callback is `https://notebook-factory-green.vercel.app/api/auth/callback`. Origin checks and iframe configuration also depend on the same APP_URL. Preview editing requires a matching origin, OAuth configuration, and environment scope.

[[backend/main.py#headers]] installs the incoming request headers in the Vercel HeadersContext so the SDK can use deployment OIDC. The project needs Sandbox access and OIDC support. No static Vercel token is required in the deployed app.

The backend loads `backend/.env`; it does not automatically load a root `.env.local` produced by CLI environment commands. Load or export that file explicitly when using its credentials locally. Never put backend secrets in `VITE_*` variables, which are client-visible.

Marketplace connection supplies the database variables. The application reads DATABASE_URL, not the other provider-specific aliases. Required environment changes take effect in a new deployment. Startup creates missing tables and adds the published HTML column to existing tables. Existing publications backfill HTML on first read. Other future schema changes need an explicit migration strategy.

## Local development

[[frontend/vite.config.ts]] proxies browser `/api` requests to FastAPI on port 8000. The standard local app origin is `http://localhost:5173`.

From the repository root:

```sh
cp backend/.env.example backend/.env
uv sync --project backend
npm ci --prefix frontend
```

Configure a local GitHub OAuth application with callback `http://localhost:5173/api/auth/callback`, then run these in separate terminals:

```sh
cd backend
uv run uvicorn main:app --reload --port 8000
```

```sh
npm run dev --prefix frontend
```

Local SQLite needs no service provisioning. Live editing still requires Sandbox credentials. The Python package supports 3.12+, while the checked-in version file selects 3.13. Vite requires a compatible Node runtime; setup used Node 24.

For the Vercel local gateway, use the verified published CLI and match OAuth to port 3000:

```sh
APP_URL=http://localhost:3000 VERCEL_ENV=development npx vercel@62.1.0 dev -L
```

## Deploy procedure

[vercel.json](../vercel.json) is the deployable Services definition. Published Vercel CLI 62.1.0 was verified; the previously installed custom 50.37.2 build rejected this Services configuration.

Run from the repository root, retaining the existing project link:

```sh
npx vercel@62.1.0 link
npx vercel@62.1.0 env ls production
sh scripts/deploy.sh --prod --yes
```

Linking is only needed on an unlinked checkout. Set or connect required environment variables before deploying. Use the root as the Vercel project directory, not the frontend or backend subdirectory. Dependency lockfiles and bundled templates must be included in the deployment.

After deployment, confirm the production alias serves the updated frontend and `/api/health` returns 200. Follow [[verification#Live checks]] to validate database, OAuth, streaming, and actual notebook execution; liveness alone does not cover them.

## Troubleshooting

Use production request logs to distinguish function initialization, rendering, Sandbox provisioning, and browser bridge failures. [[editing]] describes the boundaries between those operations.

```sh
npx vercel@62.1.0 logs --environment production --since 10m --limit 100 --json
```

| Symptom | Checks grounded in the implementation |
| --- | --- |
| Root page is a Vercel 404 | Repository root selected; both Services present; frontend catch-all is `/(.*)` |
| API initialization fails | Required secret, HTTPS APP_URL, durable DATABASE_URL, and correct environment scope |
| Render endpoint returns 500 | Bundled templates deployed and explicit nbconvert template paths intact |
| OAuth/origin rejection | OAuth callback, APP_URL, browser origin, session, and owner login agree |
| Setup stops or errors | Live stage/output, OIDC/Sandbox access, install deadline, Jupyter readiness logs |
| Editor operation returns 409 | Another operation owns the lease or the editor token is stale |
| Editor returns 410 | Sandbox expired/unavailable; reopen from the last durable draft |
| Close feels slow | Notebook save and database persistence precede success; Sandbox shutdown runs afterward |

Jupyter output is redirected to `.jupyter.log` inside the Sandbox. Startup failures retain a bounded excerpt and redact the capability token there. General SDK HTTP logs can still contain sensitive capability URLs; redact them before sharing. Do not restart or stop an active user Sandbox merely to inspect it.


## Published HTML in Blob

[[backend/publication.py]] uploads published HTML to the public `notebook-factory-rendered` store (`store_tQonYaLi3LNwbxCH`, iad1), connected to production. Drafts and notebook source remain in Postgres.

Each publication gets a unique URL with a long cache lifetime. Metadata includes the URL, letting the browser fetch directly from Blob without an additional database render request. HTML is served as a download by Blob, so the frontend fetches it and uses iframe srcdoc. A CSP meta tag inside the artifact preserves content restrictions alongside the iframe sandbox.

The database retains rendered HTML as a fallback. Without Blob credentials, local development uses the original render endpoint. A failed CDN fetch falls back to that endpoint. Existing rows upload their stored HTML once when the render endpoint is visited, guarded by publication revision. Upload failure prevents switching the published database record.

Previously published Blob URLs remain public; this implementation does not garbage-collect old versions or uploads left behind by failed database commits. The Blob store contains only documents submitted for publication, never ordinary autosaved drafts.

## Prepared font assets

[scripts/deploy.sh](../scripts/deploy.sh) runs [[scripts/prepare_fonts.py#prepare]] before the Vercel deploy. Unchanged recipes reuse the committed immutable Blob manifest without rebuilding or requiring Blob credentials locally.

When changing the preparation script, run `uv run scripts/prepare_fonts.py` with BLOB_READ_WRITE_TOKEN set, or pass `--env-file` pointing to a private environment file. Commit the resulting [manifest](../backend/assets/fonts.json) alongside the script. The builder pins fontTools and upstream font checksums; the recipe hash invalidates prepared assets when its source changes. Git-based deployments use the committed manifest directly. Blob credentials remain outside the Sandbox, which only receives a public asset URL and checksum.
