# Notebook editing

A notebook's durable document lives in Postgres. JupyterLab provides temporary execution and editing in a Sandbox, coordinated by the app's save bridge and database lease.

## Provisioning

[[backend/main.py#provision_editor]] reuses a reachable editor or creates a replacement from the durable draft. Transient provider failures preserve the existing session instead of silently replacing it.

[[backend/editor.py#start]] creates a randomly named Sandbox with port 8888 and an initial 15-minute execution limit. It writes `notebook.ipynb`, creates a Python 3.13 virtual environment with uv, and installs pinned JupyterLab 4.4.10 and pysqlite3-binary.

Each new Sandbox installs its environment from scratch; there is no prebuilt snapshot cache. Installation has a 220-second process deadline. After configuration, the backend starts Jupyter and polls its public route for up to 45 seconds before declaring failure.

Files in [backend/assets](../backend/assets) supply focused editor CSS, the message bridge, a SQLite compatibility shim, a launcher, and a template patch. These were adapted from `/Users/yury/dev/vercel/vercel-py`, branch `nb_next`, commit `8296336`; the upstream license is retained in [backend/assets/LICENSE](../backend/assets/LICENSE).

[[backend/assets/patch_jupyter_template.py]] patches the installed Jupyter application HTML while preserving its bundle references. [[backend/assets/jupyter_launcher.py]] derives root, settings, and template paths from its own location instead of assuming `/vercel/sandbox` is the workspace.

## Editor isolation

[[backend/editor.py#start]] protects Jupyter routes with a random 256-bit capability path. The editor URL is returned only to the authorized owner and stored with the notebook's session record.

Jupyter's own token/password authentication and XSRF checks are disabled for this capability-based integration. Anyone holding the editor URL can use that running environment. The URL must not be included in public notebook responses or documentation.

The Jupyter response restricts framing to the configured app origin. [[backend/assets/jupyter_bridge.js]] separately checks parent window, origin, request ID, and capability token before accepting save messages. This avoids relying on third-party cookies for the embedded editor.

## Live setup progress

[[backend/main.py#open_editor]] supports a streamed POST response when Accept includes `text/event-stream`. [[frontend/src/main.tsx#startEditor]] consumes the stream with fetch, including messages split across network chunks.

Each event is a JSON object inside an SSE `data:` frame:

| Type | Payload and behavior |
| --- | --- |
| `progress` | `message` names the current provisioning stage |
| `log` | `message` contains incremental installer output |
| `ready` | `editor` contains the session name, URL, and token; ends setup |
| `error` | `message` explains failure; ends setup |

The server sends heartbeat comments every ten seconds while waiting and disables proxy buffering with `X-Accel-Buffering: no`. Authentication and missing-notebook errors happen before streaming; subsequent errors use the event contract.

[[backend/editor.py#SetupOutput]] forwards SDK stdout/stderr, strips ANSI escapes, limits forwarded installation output to 100,000 characters, and retains a bounded diagnostic tail. The browser keeps the last 20,000 characters, scrolls output, and shows elapsed seconds. It retains failed setup output for inspection.

The stream owns the provisioning task and cancels it on disconnect. Provisioning and lease cleanup have cancellation handling. Ordinary callers without the streaming Accept header retain the JSON endpoint behavior.

## Saving and publication

[[frontend/src/main.tsx]] requests a bridge save before calling the backend. The bridge waits for the notebook context to be ready and saved, without waiting for full Jupyter workspace restoration.

A bridge response must arrive within 20 seconds. Every 30 seconds, the frontend saves a durable draft, skipping an autosave if another save/close is active. The backend reads the current notebook through Jupyter's file route, validates it, and commits it to Postgres.

[[backend/editor.py#read]] bounds the HTTP read by the notebook size limit, checks session availability, and normally extends Sandbox execution time by 30 seconds. [[backend/main.py#save_draft]] stores the document and outputs; it never executes cells.

Publish copies the same saved document into the public version, increments the revision, updates publication time, and refreshes the rendered iframe. It does not run cells, stop the editor, deploy the application, or retain previous revisions.

## Closing and recovery

[[backend/main.py#close]] saves the draft and clears the current editor record before returning success. [[backend/main.py#stop_closed_editor]] stops the detached Sandbox as a response background task.

Closing skips the unnecessary Sandbox time extension. The iframe is detached after Jupyter confirms its save, so server shutdown cannot surface a kernel-death dialog in the visible editor. Failed persistence restores the iframe and does not stop the Sandbox.

Background shutdown errors are logged; the Sandbox execution limit bounds its remaining lifetime. This background task is not a durable job queue. Reopening after close provisions a fresh environment from the stored draft.

Notebook documents and their saved outputs persist. Kernel memory, uploaded side files, and extra installed dependencies do not. Closing the browser stops app autosaves/heartbeats, so changes since the last successful durable save can be lost. A before-unload warning is advisory, not persistence.
