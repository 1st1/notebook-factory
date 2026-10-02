# Notebook Factory

A public Python notebook library with GitHub-owner-only editing. React and FastAPI run as Vercel Services; temporary JupyterLab environments run in Vercel Sandbox.

## Product scope

[[frontend/src/main.tsx]] provides notebook navigation, title search, creation, public rendering, downloads, and an embedded editor for GitHub user 1st1.

The selected notebook is reflected in the `notebook` URL query parameter. Public readers see published content; owner edits remain private until Save & exit. Creation immediately publishes the starter notebook at revision 1. There is no separate unpublished-notebook state.

Titles are set at creation. Rename, deletion, notebook upload, revision history, and collaborative editing are not implemented. A revision is a counter, not a stored historical snapshot. [[editing]] describes the editor lifecycle.

## Services

[vercel.json](../vercel.json) routes `/api/:path*` to the FastAPI service rooted at `backend` and `/(.*)` to the Vite service rooted at `frontend`.

The API entrypoint is `main:app`, with a 300-second function limit. The catch-all deliberately uses `/(.*)`: the previous `/:path*` form missed the bare root path in production. Deploy the repository root so both services and rewrites are included.

[frontend/package.json](../frontend/package.json) defines React 19, TypeScript, Vite, and Lucide dependencies. [backend/pyproject.toml](../backend/pyproject.toml) defines FastAPI, SQLAlchemy, asyncpg, nbformat, nbconvert, and the Python Sandbox SDK; the lockfiles resolve installed versions. [backend/.python-version](../backend/.python-version) selects Python 3.13.

Browser API calls stay on the app origin. Editor HTTP and WebSocket traffic connects directly to the Sandbox origin; Functions do not proxy kernel WebSockets. Postgres stores durable notebook state. See [[deployment]] for the actual project configuration.

## Persistence

[[backend/db.py]] owns the notebook table and async SQLAlchemy engine. Postgres is required on Vercel; local development defaults to a SQLite file in the backend directory.

| Fields | Meaning |
| --- | --- |
| `id`, `title` | UUID identity and creation-time display title |
| `source` | Latest durable private draft, including saved cell outputs |
| `published` | Notebook document exposed by public render and download endpoints |
| `render_url` | Immutable public Blob URL for rendered HTML; included in notebook metadata |
| `published_html` | Pre-rendered HTML for the same published revision; nullable for legacy rows |
| `created_at`, `updated_at`, `revision` | Creation/publication metadata; draft saves do not change publication time |
| `editor` | Nullable JSON containing Sandbox name, editor URL, and capability token |
| `claim`, `claim_until` | Atomic operation lease shared across function instances |

[[backend/db.py#initialize]] creates missing tables under a Postgres transaction advisory lock. Initialization also adds the nullable published HTML column to existing tables. This targeted upgrade is not a general migration framework. Postgres retains up to two idle connections with three overflow connections, pre-ping checks, and five-minute recycling to avoid repeating connection setup on every request. SQLite tests use NullPool. Application shutdown disposes the pool.

[[backend/config.py]] normalizes conventional Postgres URLs for asyncpg, maps `sslmode` to `ssl`, and removes libpq's `channel_binding` option. Deployment startup rejects missing or non-Postgres database configuration.

[[backend/main.py#editor_lease]] serializes create-editor, save, and close operations with a five-minute database lease. Conflicting operations return 409. Lease release matches the claim token, so one request cannot clear another request’s lease.

## Public rendering

[[backend/render.py#render]] converts notebooks to HTML during creation and publication. Public views fetch published HTML from Blob’s CDN into a sandboxed iframe, without executing cells or running nbconvert. [[backend/render.py#validate]] enforces valid notebook structure and the size limit from [[backend/config.py#MAX_BYTES]].

Lab and base templates are bundled in [backend/templates](../backend/templates), with explicit template search paths. Functions cannot rely on system-installed Jupyter data directories. Public downloads also return `published`, even for the signed-in owner.

The rendered iframe and API response both enforce sandboxing. The CSP blocks network connections and nested frames while permitting selected script CDNs, styles, fonts, and images. Some interactive outputs therefore do not work publicly. HTML conversion runs off the API event loop. Blob upload completes first, then source, fallback HTML, Blob URL, and revision are published in one transaction; rendering failure preserves the prior publication. Legacy rows render once on first read, with a revision-guarded cache write that cannot overwrite a newer publication. Notebook listings select metadata only.

## Authentication

[[backend/auth.py]] uses GitHub OAuth and signed, expiring cookies. [[backend/auth.py#require_owner]] enforces the 1st1 login and exact application Origin on every notebook mutation.

OAuth requests `read:user`. A signed state cookie expires after ten minutes; the signed session expires after seven days. Cookies are HttpOnly, SameSite=Lax, and Secure on HTTPS. The access token is used to fetch identity, not persisted in the session.

The owner check is case-insensitive on the GitHub login, not pinned to a numeric account ID. The frontend hides editing controls for other users, while the backend independently rejects unauthorized requests. There is no development authentication bypass.

Public notebook metadata excludes drafts, editor capabilities, and leases. Responses use no-store caching and no-referrer headers. Logout requires the configured Origin, and the UI disables logout while an editor is open.

## API contracts

[[backend/main.py]] exposes public reads and owner-only mutations. [[backend/auth.py]] provides identity, OAuth login/callback, and logout routes.

| Route | Contract |
| --- | --- |
| `GET /api/notebooks` | Public metadata ordered by publication update time |
| `POST /api/notebooks` | Owner creates a starter notebook from a nonblank title, returning 201 |
| `GET /api/notebooks/{id}/render` | Published HTML with isolation headers |
| `GET /api/notebooks/{id}/download` | Published `.ipynb` attachment |
| `POST /api/notebooks/{id}/editor` | Owner opens/reuses an editor; JSON or event stream depending on Accept |
| `POST /api/notebooks/{id}/save` | Validates session token, persists draft, optionally publishes |
| `POST /api/notebooks/{id}/close` | Persists draft, detaches editor, schedules Sandbox shutdown |
| `POST /api/notebooks/{id}/discard` | Discards draft, restores published source, and schedules shutdown |
| `GET /api/auth/me` | Identity, edit permission, and OAuth configuration status |
| `GET /api/health` | Process liveness only; does not query Postgres or Sandbox |

Save and close require the current editor capability token in the JSON body. Stale tokens return 409; expired/unavailable editors can return 410; oversized or invalid notebook documents return 413 or 422. Setup errors after streaming begins arrive as events, not a changed HTTP status.

## Editing

[[editing]] documents provisioning, the save bridge, progress events, and temporary-environment behavior. [[backend/editor.py]] is the Python SDK boundary; [[frontend/src/main.tsx]] coordinates the browser lifecycle.

## Authorization tests

[[backend/tests/test_app.py]] checks anonymous, non-owner, and cross-origin mutations, forged cookies, OAuth state rejection, and anonymous access to the setup stream.

## Persistence tests

[[backend/tests/test_app.py]] checks private/public separation, editor reuse, stale sessions, failure recovery, concurrent startup, and save-before-shutdown behavior.

It also checks bundled rendering templates, workspace-relative launcher paths, progress events, and lease release after startup failure. [[verification]] describes how to run the suite and what requires live infrastructure.


## Viewport layout

[Frontend styles](../frontend/src/style.css) fixes the app to the dynamic viewport height and suppresses outer document scrolling and overscroll. The notebook surface fills the remaining space below the notebook title and actions.

Notebook and chat panels share compact, aligned headers; chat actions are grouped at the right. Errors appear below the workspace with matching horizontal margins. Title spacing is compact.

A subtle GitHub icon beside the sidebar logo opens the project repository in a new tab. The breadcrumb toolbar is omitted. A standalone mobile navigation button opens the sidebar on narrow screens.

Published and editor iframes scroll internally rather than imposing minimum heights on the page. The sidebar notebook list scrolls independently with overscroll disabled; sidebar branding and account controls stay fixed. Setup output has a bounded scroll area. Compact spacing preserves notebook space on short landscape screens.

## Workspace startup

The public notebook list renders independently of authentication. A five-minute, tab-local metadata cache lets return visits show the published notebook immediately while fresh metadata loads.

[[frontend/src/main.tsx#cachedNotebooks]] stores only the public list and published render URLs in session storage. Auth and edit permissions are never cached. Fresh list responses replace cached entries and reconcile selection; unavailable storage falls back to normal loading. [[backend/db.py]] reuses bounded Postgres connections for warm requests.
