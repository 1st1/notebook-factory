# Notebook chat

The editor's Chat button opens a right sidebar where the assistant can read, edit, and execute the active notebook using Python AI SDK and AI SDK UI.

[[frontend/src/Chat.tsx#Chat]] uses useChat and DefaultChatTransport. [[backend/main.py#notebook_chat]] requires owner authentication, same-origin requests, and an active editor token on every model turn. History is ephemeral and disappears when the editor closes.

## Agent and streaming

[[backend/chat.py]] streams through Vercel AI Gateway with four browser-executed notebook tools. The model never receives Sandbox credentials or a general server-side execution tool.

The default model is Claude Sonnet 4.6, configurable with AI_MODEL. Deployment uses Vercel OIDC; local development can load VERCEL_OIDC_TOKEN or AI_GATEWAY_API_KEY. Gateway access and credits are required. Notebook sources and text outputs are sent to the model when it reads the document.

The Python 0.8 UI adapter dispatches completed client tool inputs through an empty ToolCallResult event. Continuations preserve the existing assistant UI message ID to prevent duplicated tool history. Empty argument strings are normalized to JSON objects. Requests have a 1 MB history limit and 160-message limit; the browser bounds automatic work to 24 tool calls per user message.

## Live document tools

The [Jupyter bridge](../backend/assets/jupyter_bridge.js) operates on the current notebook's shared model, including unsaved changes. It never replaces notebook files behind Jupyter's document context.

Read returns cell IDs, sources, and text/error outputs, excluding image data. Replace and run require exact expected source, rejecting stale edits. Insert creates a new code or markdown cell; execution uses Jupyter's run-cell command so outputs and charts appear normally. Tools serialize and validate the parent origin, window identity, session token, and request ID.

Exit, Save & exit, and notebook navigation are disabled during assistant work. Closing the chat sidebar keeps the session running. Stop reply cancels model streaming and skips queued tools; an already-started cell continues running and can be interrupted in Jupyter. Tool response waits time out after two minutes. Normal draft autosaving, explicit publication, and discard semantics still apply.

## Live document tests

Bridge regression tests verify reads see live source, stale replacements fail, legitimate replacements succeed, and untrusted origins or windows cannot invoke tools.

The test uses a document model double; real Sandbox checks additionally exercise Jupyter commands and Python kernel output.

## Chat authorization tests

API regressions verify owner and origin requirements, rejection of stale editor capabilities, and the chat history size limit before any model request.

## Streaming protocol tests

Live Sandbox checks verified reading, insertion, source replacement, kernel outputs (42 and 49), dependency installation, and an inline matplotlib chart. Five desktop/mobile viewport sizes fit without outer scrolling.

A simulated Python model stream verifies that the UI adapter emits executable client tool inputs without a fabricated tool result and terminates the SSE stream correctly.
