# Notebook chat

Chat is available while viewing or editing a notebook. Viewing answers use published content without a Sandbox; edits and execution require an editor, opened through explicit Yes/No consent.

[[frontend/src/Chat.tsx#Chat]] uses useChat and DefaultChatTransport. [[backend/main.py#notebook_chat]] requires owner authentication, same-origin requests, and validates an editor token when supplied. Tokenless owner requests use the restricted viewing prompt and tools. Cmd+Enter or Ctrl+Enter submits the chat composer; plain Enter inserts a newline. History is private, stored per notebook in Postgres, and restored when the editor reopens.

## Agent and streaming

[[backend/chat.py]] streams through Vercel AI Gateway with five browser-executed document tools and an authenticated notebook rename tool. The model never receives Sandbox credentials or a general server-side execution tool.

The default model is GPT-6 Luna, configurable with AI_MODEL. The chat header displays the model ID returned by the server, using the same configuration as inference. Medium reasoning effort requests reasoning; provider-visible reasoning is optional, and the UI streams it in an expandable Thoughts section, open while streaming and collapsed afterward. A spinner accompanies waiting and tool-execution status. Deployment uses Vercel OIDC; local development can load VERCEL_OIDC_TOKEN or AI_GATEWAY_API_KEY. Gateway access and credits are required. A free-tier model rejection displays an explicit instruction to add paid Gateway credits. Notebook sources and text outputs are sent to the model when it reads the document.

The Python 0.8 UI adapter dispatches completed client tool inputs through an empty ToolCallResult event. Continuations preserve the existing assistant UI message ID to prevent duplicated tool history. Empty argument strings are normalized to JSON objects. Requests have a 1 MB history limit and 160-message limit; the browser bounds automatic work to 24 tool calls per user message. The prompt makes that budget explicit and defaults open-ended demonstrations to one focused example with a few cells and one result; multiple examples require an explicit request. Final explanations, conclusions, and caveats belong in a Markdown cell after the relevant notebook work, updating an existing conclusion when appropriate. The assistant reserves tool budget to write and reveal those remarks, then confirms briefly in chat. Explicit chat-only requests take precedence; tool failures are reported without claiming the remarks were saved.

## Live document tools

The [Jupyter bridge](../backend/assets/jupyter_bridge.js) operates on the current notebook's shared model, including unsaved changes. It never replaces notebook files behind Jupyter's document context.

Read returns cell IDs, sources, and text/error outputs, excluding image data. Replace and run require exact expected source, rejecting stale edits. Insert creates a new code or markdown cell; execution uses Jupyter's run-cell command so outputs and charts appear normally. The scroll tool moves the notebook up/down by a page, to its top/bottom, or to a cell ID with start/center/end alignment. It uses Jupyter's virtualized-list API to reveal offscreen cells without changing selection or notebook content. The prompt instructs the assistant to reveal edited cells and outputs. Tools serialize and validate the parent origin, window identity, session token, and request ID.

Save & exit and notebook navigation are disabled during assistant work. Closing the chat sidebar keeps the session running. Stop reply cancels model streaming and skips queued tools; an already-started cell continues running and can be interrupted in Jupyter. Tool response waits time out after two minutes. Normal draft autosaving, explicit publication, and discard semantics still apply.

## Live document tests

Bridge regression tests verify reads see live source, stale replacements fail, legitimate replacements succeed, and untrusted origins or windows cannot invoke tools.

The test uses a document model double; real Sandbox checks additionally exercise Jupyter commands and Python kernel output.

## Chat authorization tests

API regressions verify owner and origin requirements, rejection of stale editor capabilities, and the chat history size limit before any model request.

## Streaming protocol tests

Live Sandbox checks verified reading, insertion, source replacement, kernel outputs (42 and 49), dependency installation, and an inline matplotlib chart. Five desktop/mobile viewport sizes fit without outer scrolling.

A simulated Python model stream verifies that the UI adapter emits executable client tool inputs without a fabricated tool result and terminates the SSE stream correctly.

## Unfocused notebook saves

The bridge resolves notebook.ipynb among Jupyter's open main-area widgets when the focused widget is absent or different. Saving and chat tools therefore do not require focus inside the notebook.

Execution activates the resolved notebook before invoking Jupyter's cell command. A regression test removes the focused widget and verifies that saving still reaches the open document.

## Notebook scrolling tests

Bridge tests verify page scrolling is confined to the notebook, cell IDs resolve through Jupyter's virtualized list, and invalid directions or missing targets fail without changing content.

## Bridge compatibility and recovery

Chat checks the embedded bridge protocol before invoking tools. The handshake also reports document readiness, so tools wait for loading. Expired runtimes recover automatically; timed-out cell execution is never blindly replayed.

Unknown tools are rejected before cell lookup. Source conflicts return the current cell ID and bounded source so the assistant can adapt its operation; missing cells require a fresh read. The prompt requires using new source after replacements and skipping unavailable scrolling. Three consecutive tool failures pause automatic continuation. The exact-source guard remains in place to protect newer edits and prevent execution of unexpected code.

An authenticated handshake regression runs before document readiness; document tests cover stale source recovery, missing cells, and unknown tool rejection.

## Tool argument streaming

[[frontend/src/ToolActivity.tsx#ToolActivity]] shows partial tool arguments as the model generates them, including a growing cell-source preview. Completed operations collapse into expandable input and result details.

Tool cards distinguish argument generation from execution and errors. Code previews scroll within a bounded area; result previews are capped at 12 KB. The Python SDK forwards argument deltas immediately, while execution still waits for complete arguments. A protocol regression verifies deltas arrive before completion and dispatch; browser checks verify code appears before a cell tool executes. Execution output is displayed when the tool finishes, not streamed from the kernel.

## Chat Markdown and model label

Chat renders GitHub-flavored Markdown tables in horizontally scrollable containers. The server reports the configured model ID, which is displayed below the chat toolbar.

[[backend/config.py#chat_model]] supplies both inference and [[backend/auth.py#me]] so environment overrides cannot leave a hardcoded model label behind. A regression verifies both the default and override values. Browser checks cover table headers, cells, and narrow-panel overflow.

## Persistent conversations

[[frontend/src/useNotebookHistory.ts#useNotebookHistory]] loads the notebook conversation and saves it after each completed or stopped turn. History survives publishing, discarding edits, reconnecting, and reopening the editor.

History loading disables only chat controls, not sidebar navigation. Active assistant work and pending history writes still block navigation to preserve the conversation.

[[backend/main.py#load_chat_history]] and [[backend/main.py#save_chat_history]] require the owner and same-origin requests. The UI saves history independently of the editor token so a viewing-to-editing handoff preserves the same conversation; legacy token-bearing calls still validate that token. Revision checks reject concurrent stale writes, and private history is excluded from public notebook metadata and exports. Storage uses the existing one-megabyte and 160-message limits. New chat clears the saved conversation; it does not change notebook content.

[[backend/chat.py#history_messages]] marks unfinished tools as interrupted when storing them. Rehydration does not submit model requests or replay tools; the next user message begins a fresh turn. The prompt treats previous results as historical because notebook edits may have been discarded and kernel memory may have changed.

Navigation and editor exit wait for pending history saves. Save failures remain visible with a retry action; conflicts offer reloading the saved chat instead of overwriting it. Completed turns are durable; forcibly closing the browser mid-reply can lose the unfinished turn. Authentication permissions are not cached with conversations.

## Persistent history tests

API regressions verify history survives draft discard and editor replacement, interrupted tools become inert history, stale revisions and tokens fail, New chat clears history, and public or unauthorized requests cannot read it.

Browser checks cover restoration without model/tool replay, completed-turn persistence, save failure/retry, and clearing persisted history.


## Notebook renaming

The assistant can rename the current notebook when the user asks. The header, sidebar, and cached notebook metadata update immediately after a successful response.

The rename tool calls [[backend/main.py#rename_notebook]], requiring owner authentication, exact Origin, and the current editor token under the editor lease. Titles are trimmed, nonempty, and limited to 120 characters. This changes public workspace metadata immediately; it does not change cells, publication revision, or the Sandbox filename. Rename-only requests receive a brief chat confirmation without adding notebook cells.

## Notebook rename tests

API coverage checks owner and Origin enforcement, stale editor tokens, blank and oversized titles, persistence of trimmed titles, and preservation of published document contents.

## Viewing mode tests

Owner chat works without an editor and does not start a Sandbox. Its tools are limited to reading the published document and requesting permission to enter editing; private history remains protected and revision-checked.

[[backend/chat.py#VIEW_TOOLS]] and [[backend/chat.py#VIEW_SYSTEM]] keep explanations in chat. [[frontend/src/Chat.tsx#Chat]] reads published cells and bounded text outputs from the download endpoint. The permission tool displays Yes/No buttons. No returns a declined result without starting anything. Yes awaits editor and document readiness, then continues the same turn using the active editor token and full editing tools. The assistant rereads the live draft because it may differ from published content.

Browser verification covers published context, no Sandbox on questions or refusal, accepting consent, retaining the conversation, and authenticated mode changes on continuation. Chat remains owner-only in both modes.
