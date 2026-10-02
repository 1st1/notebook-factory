import { useChat } from "@ai-sdk/react";
import {
  DefaultChatTransport,
  lastAssistantMessageIsCompleteWithToolCalls,
} from "ai";
import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import Markdown from "react-markdown";
import { Send, Square, X, RotateCcw } from "lucide-react";

export function Chat({
  notebookId,
  editor,
  frame,
  open,
  onClose,
  onBusy,
  disabled,
}: {
  notebookId: string;
  editor: { url: string; token: string };
  frame: RefObject<HTMLIFrameElement | null>;
  open: boolean;
  disabled: boolean;
  onClose: () => void;
  onBusy: (busy: boolean) => void;
}) {
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(0);
  const active = useRef(true);
  const count = useRef(0);
  const halted = useRef(false);
  const tail = useRef(Promise.resolve());
  const bottom = useRef<HTMLDivElement>(null);
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `/api/notebooks/${notebookId}/chat`,
        body: { token: editor.token },
      }),
    [notebookId, editor.token],
  );
  const {
    messages,
    sendMessage,
    addToolOutput,
    status,
    error,
    stop,
    setMessages,
    clearError,
  } = useChat({
    transport,
    sendAutomaticallyWhen: (options) =>
      !halted.current &&
      count.current < 24 &&
      lastAssistantMessageIsCompleteWithToolCalls(options),
    onToolCall({ toolCall }) {
      setPending((n) => n + 1);
      const work = tail.current.then(async () => {
        try {
          if (!active.current) return;
          if (disabled) throw new Error("The editor is closing.");
          if (halted.current) throw new Error("Stopped by user.");
          if (++count.current > 24)
            throw new Error(
              "Tool limit reached. Send another message to continue.",
            );
          const target = frame.current?.contentWindow;
          if (!target) throw new Error("Editor is unavailable.");
          const origin = new URL(editor.url).origin;
          const id = crypto.randomUUID();
          const output = await new Promise<unknown>((resolve, reject) => {
            const timer = window.setTimeout(() => {
              cleanup();
              reject(
                new Error(
                  "Jupyter timed out. A running cell may still be executing; inspect it before retrying.",
                ),
              );
            }, 120000);
            function cleanup() {
              clearTimeout(timer);
              window.removeEventListener("message", receive);
            }
            function receive(event: MessageEvent) {
              if (
                event.source !== target ||
                event.origin !== origin ||
                event.data?.id !== id ||
                event.data.type !== "vercel-notebook-tool-result"
              )
                return;
              cleanup();
              if (event.data.error) reject(new Error(event.data.error));
              else resolve(event.data.result);
            }
            window.addEventListener("message", receive);
            target.postMessage(
              {
                type: "vercel-notebook-tool",
                token: editor.token,
                id,
                tool: toolCall.toolName,
                args: toolCall.input,
              },
              origin,
            );
          });
          if (active.current)
            await addToolOutput({
              tool: toolCall.toolName,
              toolCallId: toolCall.toolCallId,
              output,
            });
        } catch (error) {
          if (active.current)
            await addToolOutput({
              tool: toolCall.toolName,
              toolCallId: toolCall.toolCallId,
              output: {
                error: error instanceof Error ? error.message : "Tool failed",
              },
            });
        } finally {
          if (active.current) setPending((n) => n - 1);
        }
      });
      tail.current = work.catch(() => {});
    },
  });
  const busy = status === "submitted" || status === "streaming" || pending > 0;
  useEffect(() => {
    onBusy(busy);
  }, [busy, onBusy]);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      void stop();
      onBusy(false);
    };
  }, [stop, onBusy]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages, pending]);
  return (
    <aside className="chat-panel" hidden={!open} aria-label="Notebook chat">
      <header className="surface-toolbar">
        <span><span className="green-dot" />NOTEBOOK CHAT</span>
        <span className="chat-header-actions">
        <button
          className="icon-button"
          aria-label="New chat"
          title="New chat"
          disabled={busy}
          onClick={() => {
            setMessages([]);
            clearError();
            count.current = 0;
          }}
        >
          <RotateCcw size={16} />
        </button>
        <button
          className="icon-button"
          aria-label="Close chat"
          onClick={onClose}
        >
          <X size={18} />
        </button>
        </span>
      </header>
      <div className="chat-messages" aria-live="polite">
        {!messages.length && (
          <p className="chat-hint">
            Ask me to fix a bug, explain a cell, or plot a chart. I can edit and
            run cells in this notebook. Changes stay in your draft.
          </p>
        )}
        {messages.map((message) => (
          <div className={`chat-message ${message.role}`} key={message.id}>
            <small>{message.role === "user" ? "You" : "Assistant"}</small>
            {message.parts.map((part, index) =>
              part.type === "text" ? (
                <Markdown key={index}>{part.text}</Markdown>
              ) : part.type.startsWith("tool-") ||
                part.type === "dynamic-tool" ? (
                <div className="chat-tool" key={index}>
                  {"toolName" in part
                    ? String(part.toolName)
                    : part.type.slice(5)}{" "}
                  ·{" "}
                  {"state" in part
                    ? String(part.state).replaceAll("-", " ")
                    : ""}
                  {"output" in part &&
                  part.output &&
                  typeof part.output === "object" &&
                  "error" in part.output ? (
                    <p className="chat-error">{String(part.output.error)}</p>
                  ) : null}
                </div>
              ) : null,
            )}
          </div>
        ))}
        {busy && (
          <p className="chat-hint">
            {pending ? "Working in Jupyter…" : "Thinking…"}
          </p>
        )}
        {count.current >= 24 && !busy && (
          <p className="chat-hint">
            Tool limit reached. Send another message to continue.
          </p>
        )}
        {error && (
          <p role="alert" className="chat-error">
            {error.message}
          </p>
        )}
        <div ref={bottom} />
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!input.trim() || busy || disabled) return;
          count.current = 0;
          halted.current = false;
          void sendMessage({ text: input });
          setInput("");
        }}
      >
        <textarea
          aria-label="Message"
          placeholder="Ask about this notebook…"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!event.repeat) event.currentTarget.form?.requestSubmit();
            }
          }}
          aria-keyshortcuts="Meta+Enter Control+Enter"
          disabled={busy || disabled}
          rows={3}
        />
        <div>
          {busy ? (
            <button
              type="button"
              className="button"
              onClick={() => {
                halted.current = true;
                void stop();
              }}
            >
              <Square size={14} />
              Stop reply
            </button>
          ) : (
            <button
              className="button primary"
              disabled={!input.trim() || disabled}
            >
              <Send size={14} />
              Send
            </button>
          )}
        </div>
        {pending > 0 && (
          <small>
            A started cell keeps running even if you stop the reply.
          </small>
        )}
      </form>
    </aside>
  );
}
