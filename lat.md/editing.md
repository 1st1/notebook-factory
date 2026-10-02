# Notebook editing

A notebook's durable document lives in Postgres. JupyterLab provides temporary execution and editing in a Sandbox, coordinated by the app's save bridge and database lease.

## Provisioning

[[backend/main.py#provision_editor]] reuses a reachable editor or creates a replacement from the durable draft. Transient provider failures preserve the existing session instead of silently replacing it.

[[backend/editor.py#start]] creates a randomly named Sandbox with port 8888 and an initial 15-minute execution limit. It writes `notebook.ipynb`, creates a Python 3.13 virtual environment with uv and seeded pip, and installs pinned JupyterLab 4.4.10 and pysqlite3-binary.

Users and the assistant can run `%pip install numpy matplotlib` in a code cell to install packages into the active kernel environment. The assistant prompt recommends this notebook-native syntax.

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

[[backend/editor.py#SetupOutput]] forwards SDK stdout/stderr, strips ANSI escapes, limits forwarded installation output to 100,000 characters, and retains a bounded diagnostic tail. The browser keeps the last 20,000 characters, scrolls output, and shows elapsed seconds. It retains failed setup output for inspection. The setup panel shares the notebook surface’s responsive horizontal margins, and long log lines wrap within the panel.

The stream owns the provisioning task and cancels it on disconnect. Provisioning and lease cleanup have cancellation handling. Ordinary callers without the streaming Accept header retain the JSON endpoint behavior.

## Saving and publication

[[frontend/src/main.tsx]] requests a bridge save before calling the backend. The bridge waits for the notebook context to be ready and saved, without waiting for full Jupyter workspace restoration.

A bridge response must arrive within 20 seconds. Every 30 seconds, the frontend saves a durable draft, skipping an autosave if another save/close is active. The backend reads the current notebook through Jupyter's file route, validates it, and commits it to Postgres.

[[backend/editor.py#read]] bounds the HTTP read by the notebook size limit, checks session availability, and normally extends Sandbox execution time by 30 seconds. [[backend/main.py#save_draft]] stores the document and outputs; it never executes cells.

Save & exit renders the saved document once and uploads the rendered HTML to Blob and atomically stores its source, fallback HTML, and Blob URL as the public version, increments the revision, updates publication time, and refreshes the rendered iframe. It closes the editor after publication. It does not run cells, deploy the application, or retain previous revisions.

## Closing and recovery

Exit discards the private draft, including autosaved changes, and restores the last published document through [[backend/main.py#discard]]. It skips Jupyter saving, detaches the session, and schedules shutdown. Save & exit publishes through the close endpoint.

[[backend/main.py#close]] saves the draft and clears the current editor record before returning success. [[backend/main.py#stop_closed_editor]] stops the detached Sandbox as a response background task.

Closing skips the unnecessary Sandbox time extension. The iframe is detached after Jupyter confirms its save, so server shutdown cannot surface a kernel-death dialog in the visible editor. Failed persistence restores the iframe and does not stop the Sandbox.

Background shutdown errors are logged; the Sandbox execution limit bounds its remaining lifetime. This background task is not a durable job queue. Reopening after close provisions a fresh environment from the stored draft.

Notebook documents and their saved outputs persist. Kernel memory, uploaded side files, and extra installed dependencies do not. Closing the browser stops app autosaves/heartbeats, so changes since the last successful durable save can be lost. A before-unload warning is advisory, not persistence.

## Save serialization

The bridge serializes all saves on each Jupyter document context, covering native autosave, toolbar saves, and parent requests. A save finishes its disk write and metadata refresh before the next save begins.

JupyterLab 4.4.10 can otherwise overlap these operations: a second save reads a new disk hash before the first save updates the context hash, producing a false File Changed dialog. This was reproduced with one page and no external writer in a disposable Sandbox.

The queue preserves errors for the requesting caller and continues after a rejected save. It does not disable Jupyter's conflict checks or automatically overwrite external changes. The bridge is installed during Sandbox startup, so existing editors need to leave editing and reopen to receive it. Use Save & exit to preserve edits publicly; Exit discards them.

## Upstream integration comparison

The reference is `vercel-py` branch `nb_next`, commit `8296336`, under `src/vercel-notebook/vercel/_notebook`. Its Jupyter assets informed this integration, but its persistence and publication models differ.

The focused CSS, shell panel hiding, resize/refit scheduling, HTML template injection, and SQLite compatibility shim are carried over. Notebook Factory uses a light theme, pins JupyterLab in a virtual environment, and resolves launcher paths relative to the uploaded script.

The reference bridge synthesizes Cmd/Ctrl+S and polls the dirty-tab CSS marker for completion. It has no save serialization or conflict-check override. Notebook Factory instead awaits the document save API, queues saves, and verifies the parent origin as well as the window and token.

The reference requests a named persistent Sandbox with snapshot retention and only uploads the notebook when creating it. It checks for an existing Jupyter process, streams startup process output, and detects early process exit while polling readiness. Notebook Factory uses temporary Sandboxes restored from database drafts and streams installation output; Jupyter logs are retained for startup diagnostics.

Reference publishing verifies hashes of prepared notebook/HTML files and creates a Vercel deployment. Notebook Factory publishes by copying the durable draft to the database's public document. The reference's wildcard origin/frame allowances, hardcoded workspace paths, and keyboard-driven save bridge are not used here.

## Deployment generations

Editor environments belong to the deployment that created them. Opening or reconnecting after a deployment replaces an older environment instead of reusing its embedded Jupyter bridge.

[[backend/editor.py#generation]] uses Vercel's deployment ID (deployment URL fallback); local development hashes bundled editor assets, provisioning code, and Python dependency declarations. Legacy sessions without a generation are stale. There is currently no Sandbox snapshot cache; this policy governs live environment reuse.

[[backend/main.py#provision_editor]] recovers the old Sandbox's latest saved notebook into the database before provisioning its replacement. It keeps the old environment if recovery or startup fails and stops it only after the new session is committed. Once replaced, old session tokens cannot save or publish. Unopened stale environments expire normally; already-open browsers are not forcibly interrupted at deployment time.

A regression changes deployment generations, verifies same-deployment reuse, failed-replacement recovery, unpublished draft preservation, successful replacement, and stale-token rejection. Browser-only edits must reach Jupyter's normal save mechanism before recovery.

## Plot font fallback

New Sandboxes install Noto Emoji and Noto Sans JP alongside Matplotlib's default DejaVu Sans fallback, covering emoji and Japanese chart labels without hiding missing-glyph warnings.

[[backend/assets/install_fonts.py#install]] downloads OFL-licensed fonts from a pinned Google Fonts revision, verifies SHA-256 checksums, retains licenses, and configures Matplotlib before the kernel starts. Emoji are monochrome. The assistant preserves the fallback list when styling plots. A live Sandbox draw verified slot-machine and chart emoji, wave dash, and Japanese text with missing-glyph warnings treated as errors. Existing environments require reconnecting after deployment; existing plot outputs must be rerun.
