import { useEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

const labels: Record<string, string> = {
  rename_notebook: "Rename notebook",
  read_notebook: "Read notebook",
  request_editing: "Enter editing mode",
  insert_cell: "Add cell",
  replace_cell: "Edit cell",
  run_cell: "Run cell",
  scroll_notebook: "Scroll notebook",
};

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

export function ToolActivity({ name, state, input, output, errorText }: {
  name: string;
  state: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
}) {
  const args = object(input);
  const result = object(output);
  const generating = state === "input-streaming";
  const working = generating || state === "input-available";
  const error = errorText || (typeof result.error === "string" ? result.error : "");
  const editsText = name === "insert_cell" || name === "replace_cell";
  const code = typeof args.source === "string" ? args.source :
    typeof args.expected_source === "string" ? args.expected_source : "";
  const preview = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (generating && preview.current) preview.current.scrollTop = preview.current.scrollHeight;
  }, [code, generating]);
  const resultText = output === undefined ? "" : JSON.stringify(output, null, 2);
  const status = error ? "Failed" : generating ? (editsText ? "Writing cell…" : "Preparing…") :
    state === "input-available" ? (name === "run_cell" ? "Running…" : "Working…") :
    state === "output-available" ? "Done" : state.replaceAll("-", " ");
  if (!editsText) return (
    <div className="chat-tool">
      <div className="chat-tool-summary">
        {working && <LoaderCircle size={12} className="spin" aria-hidden="true" />}
        <span>{labels[name] || name}</span><small>{status}</small>
      </div>
      {error && <p className="chat-error">{error}</p>}
    </div>
  );
  return (
    <details className="chat-tool" open={working || !!error}>
      <summary>
        {working && <LoaderCircle size={12} className="spin" aria-hidden="true" />}
        <span>{labels[name] || name}</span><small>{status}</small>
      </summary>
      {code ? <>
        <div className="chat-tool-caption">{typeof args.source === "string" ? "Cell source" : "Current cell source"}{generating ? " · streaming" : ""}</div>
        <pre ref={preview} className="chat-tool-code" aria-label="Tool code preview"><code>{code}</code></pre>
      </> : Object.keys(args).length > 0 ? (
        <pre className="chat-tool-code"><code>{JSON.stringify(args, null, 2)}</code></pre>
      ) : <p className="chat-tool-caption">{generating ? "Preparing tool arguments…" : "No arguments required."}</p>}
      {error && <p className="chat-error">{error}</p>}
      {output !== undefined && <details className="chat-tool-result">
        <summary>Result</summary>
        <pre className="chat-tool-code"><code>{resultText.slice(0, 12000)}{resultText.length > 12000 ? "\n… preview truncated" : ""}</code></pre>
      </details>}
    </details>
  );
}
