import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  BookOpen,
  Check,
  Download,
  Github,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import "./style.css";
const Chat = lazy(() => import("./Chat").then(module => ({ default: module.Chat })));

type Notebook = {
  id: string;
  title: string;
  updated_at: number;
  revision: number;
  render_url?: string | null;
};
type Auth = {
  user: { login: string; avatar_url?: string } | null;
  can_edit: boolean;
  configured: boolean;
  chat_model?: string;
};
type Editor = { name: string; url: string; token: string; notebookId?: string };
async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(
    "/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal,
        },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}

async function startEditor(
  id: string,
  report: (kind: string, message: string) => void,
): Promise<Editor> {
  const response = await fetch(`/api/notebooks/${id}/editor`, {
    method: "POST",
    headers: { Accept: "text/event-stream" },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error("Setup stream is unavailable. Please retry.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) throw new Error("Setup connection ended before the editor was ready. Please retry.");
      pending += decoder.decode(value, { stream: true });
      let end;
      while ((end = pending.indexOf("\n\n")) !== -1) {
        const block = pending.slice(0, end);
        pending = pending.slice(end + 2);
        if (!block.startsWith("data: ")) continue;
        const event = JSON.parse(block.slice(6));
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "ready") return event.editor;
        report(event.type, event.message);
      }
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

function PublishedNotebook({ notebook, version }: { notebook: Notebook; version: number }) {
  const [html, setHtml] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setHtml(null);
    setFailed(false);
    if (!notebook.render_url) return;
    const controller = new AbortController();
    fetch(notebook.render_url, { signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" })
      .then(response => {
        if (!response.ok) throw new Error("Notebook unavailable");
        return response.text();
      })
      .then(setHtml)
      .catch(error => { if (error.name !== "AbortError") setFailed(true); });
    return () => controller.abort();
  }, [notebook.render_url]);
  const useBlob = notebook.render_url && !failed;
  if (useBlob && html === null) return <div className="empty" role="status">Loading notebook…</div>;
  return <iframe
    title="Rendered notebook"
    sandbox="allow-scripts allow-downloads"
    srcDoc={useBlob ? html! : undefined}
    src={useBlob ? undefined : `/api/notebooks/${notebook.id}/render?v=${version}`}
    referrerPolicy="no-referrer"
  />;
}

const WORKSPACE_CACHE = "notebook-factory:public-workspace:v1";
function cachedNotebooks(): Notebook[] | null {
  try {
    const cached = JSON.parse(sessionStorage.getItem(WORKSPACE_CACHE) || "null");
    if (cached && Date.now() - cached.saved < 300000 && Array.isArray(cached.notebooks) &&
      cached.notebooks.every((n: Notebook) => typeof n.id === "string" && typeof n.title === "string"))
      return cached.notebooks;
  } catch { /* Storage can be unavailable. */ }
  return null;
}

function App() {
  const [auth, setAuth] = useState<Auth>({
    user: null,
    can_edit: false,
    configured: false,
  });
  const [cached] = useState(cachedNotebooks);
  const [notebooks, setNotebooks] = useState<Notebook[]>(cached || []);
  const [selected, setSelected] = useState<string | null>(
    new URLSearchParams(location.search).get("notebook") || null,
  );
  const [loading, setLoading] = useState(cached === null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [setupStage, setSetupStage] = useState("");
  const [setupLog, setSetupLog] = useState("");
  const [setupStarted, setSetupStarted] = useState<number | null>(null);
  const [setupSeconds, setSetupSeconds] = useState(0);
  const setupOutput = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (setupStarted === null) return;
    const timer = setInterval(() => setSetupSeconds(Math.floor((Date.now() - setupStarted) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [setupStarted]);
  useEffect(() => {
    const output = setupOutput.current;
    if (output) output.scrollTop = output.scrollHeight;
  }, [setupLog]);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  const [readyToken, setReadyToken] = useState<string | null>(null);
  const navigation = useRef(0);
  const startingEditors = useRef(new Map<string, { sequence: number; promise: Promise<void> }>());
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const recoveries = useRef(new Set<string>());
  const snapshots = useRef(new Map<string, Promise<void>>());
  const draftQueue = useRef(new Map<string, { token: string; source: string }>());
  const draftRequests = useRef(new Map<string, Promise<void>>());
  const [pendingDrafts, setPendingDrafts] = useState(0);
  const [saved, setSaved] = useState("");
  const [mobile, setMobile] = useState(false);
  const [renderVersion, setRenderVersion] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const saving = useRef<AbortController | null>(null);
  const closingRef = useRef(false);
  const saveEpoch = useRef(0);
  const activeEditor = editor?.notebookId === selected ? editor : null;
  const editorReady = !!activeEditor && readyToken === activeEditor.token;
  const notebook = notebooks.find((n) => n.id === selected);

  const renameNotebook = useCallback((id: string, title: string) => {
    setNotebooks(items => {
      const renamed = items.map(item => item.id === id ? { ...item, title } : item);
      try { sessionStorage.setItem(WORKSPACE_CACHE, JSON.stringify({ saved: Date.now(), notebooks: renamed })); } catch { /* Storage is optional. */ }
      return renamed;
    });
  }, []);

  const refresh = useCallback(async () => {
    await Promise.all([
      api<Notebook[]>("/notebooks").then(list => {
        setNotebooks(list);
        setLoading(false);
        setSelected(current => list.some(n => n.id === current) ? current : null);
        try {
          sessionStorage.setItem(WORKSPACE_CACHE, JSON.stringify({ saved: Date.now(), notebooks: list }));
        } catch { /* Rendering must not depend on browser storage. */ }
      }),
      api<Auth>("/auth/me").then(setAuth),
    ]);
  }, []);
  useEffect(() => {
    refresh()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [refresh]);
  useEffect(() => {
    const url = new URL(location.href);
    if (selected) url.searchParams.set("notebook", selected);
    else url.searchParams.delete("notebook");
    history.replaceState({}, "", url);
  }, [selected]);

  const saveBridge = useCallback(async () => {
    if (!editor || !frame.current?.contentWindow)
      throw new Error("The editor is not ready yet.");
    const target = frame.current.contentWindow;
    const origin = new URL(editor.url).origin;
    const id = crypto.randomUUID();
    return await new Promise<string>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        cleanup();
        reject(
          new Error(
            "Could not recover the live document. Keep this tab open; this editor may need the latest recovery bridge.",
          ),
        );
      }, 20000);
      const cleanup = () => {
        clearTimeout(timer);
        window.removeEventListener("message", receive);
      };
      const receive = (event: MessageEvent) => {
        if (
          event.source !== target ||
          event.origin !== origin ||
          event.data?.id !== id
        )
          return;
        if (event.data.type === "vercel-notebook-saved") {
          cleanup();
          if (typeof event.data.source !== "string") reject(new Error("Editor did not return a notebook."));
          else resolve(event.data.source);
        }
        if (event.data.type === "vercel-notebook-save-error") {
          cleanup();
          reject(new Error(event.data.message));
        }
      };
      window.addEventListener("message", receive);
      target.postMessage(
        { type: "vercel-notebook-export", id, token: editor.token },
        origin,
      );
    });
  }, [editor]);

  const persist = useCallback(
    async (publish = false, close = false) => {
      if (!editor || !selected || editor.notebookId !== selected) return;
      if (closingRef.current || (!close && saving.current)) return;
      if (close) {
        closingRef.current = true;
        saveEpoch.current++;
        saving.current?.abort();
        saving.current = null;
      }
      const controller = new AbortController();
      if (!close) saving.current = controller;
      const epoch = saveEpoch.current;
      try {
        const source = await saveBridge();
        if (epoch !== saveEpoch.current) return;
        // Keep the live document mounted until durable persistence succeeds.
        await api(`/notebooks/${selected}/${close ? "close" : "save"}`, {
          token: editor.token,
          source,
          publish,
        }, controller.signal);
        if (epoch !== saveEpoch.current) return;
        setSaved(
          "Draft saved at " +
            new Date().toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            }),
        );
        if (publish) {
          setRenderVersion((v) => v + 1);
          void refresh().catch((e) => setError(e.message));
        }
        if (close) {
          setEditor(null);
          setSaved("");
        }
      } catch (error) {
        // A close/discard supersedes any older autosave, including its stale-token error.
        if (epoch === saveEpoch.current) throw error;
      } finally {
        if (close) closingRef.current = false;
        else if (saving.current === controller) saving.current = null;
      }
    },
    [editor, selected, saveBridge, refresh],
  );

  function flushDraft(id: string): Promise<void> {
    const running = draftRequests.current.get(id);
    if (running) return running;
    const draft = draftQueue.current.get(id);
    if (!draft) return Promise.resolve();
    const request = api(`/notebooks/${id}/close`, { ...draft, publish: false }, AbortSignal.timeout(15000)).then(() => {
      if (draftQueue.current.get(id) === draft) draftQueue.current.delete(id);
      setPendingDrafts(draftQueue.current.size);
      if (!draftQueue.current.size) setError(previous => previous === "A notebook draft is waiting to save. Keep this tab open; retrying automatically." ? "" : previous);
    }).finally(() => { draftRequests.current.delete(id); });
    draftRequests.current.set(id, request);
    return request;
  }

  function leaveEditor(): Promise<void> {
    if (!editor?.notebookId) return Promise.resolve();
    if (readyToken !== editor.token) { setEditor(null); return Promise.resolve(); }
    const existing = snapshots.current.get(editor.token);
    if (existing) return existing;
    const outgoing = editor;
    saving.current?.abort();
    saving.current = null;
    saveEpoch.current++;
    const snapshot = saveBridge().then(source => {
      draftQueue.current.set(outgoing.notebookId!, { source, token: outgoing.token });
      setPendingDrafts(draftQueue.current.size);
      setEditor(current => current?.token === outgoing.token ? null : current);
      setSaved("");
      void flushDraft(outgoing.notebookId!).catch(() => setError("A notebook draft is waiting to save. Keep this tab open; retrying automatically."));
    }).finally(() => { snapshots.current.delete(outgoing.token); });
    snapshots.current.set(outgoing.token, snapshot);
    return snapshot;
  }

  function openEditor(id: string, sequence = navigation.current): Promise<void> {
    const existing = startingEditors.current.get(id);
    if (existing?.sequence === sequence) return existing.promise;
    const promise = (async () => {
      if (existing) await existing.promise.catch(() => {});
      await loadEditor(id, sequence);
    })().finally(() => {
      if (startingEditors.current.get(id)?.promise === promise) startingEditors.current.delete(id);
    });
    startingEditors.current.set(id, { sequence, promise });
    return promise;
  }

  async function loadEditor(id: string, sequence: number) {
    if (selectedRef.current !== id || sequence !== navigation.current) return;
    setSetupStage("Connecting…"); setSetupLog(""); setSetupSeconds(0); setSetupStarted(Date.now());
    try {
      await flushDraft(id);
      if (sequence !== navigation.current) return;
      const result = await startEditor(id, (kind, message) => {
        if (sequence !== navigation.current) return;
        if (kind === "progress") setSetupStage(message);
        if (kind === "log") setSetupLog(log => (log + message).slice(-20000));
      });
      if (sequence !== navigation.current || selectedRef.current !== id) return;
      setEditor({ ...result, notebookId: id });
      setSetupStage("Loading notebook…");
      // Let the iframe and Chat props observe the new session before tools continue.
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      await new Promise<void>((resolve, reject) => {
        const requestId = crypto.randomUUID();
        const origin = new URL(result.url).origin;
        const cleanup = () => { clearInterval(poll); clearTimeout(timeout); window.removeEventListener("message", receive); };
        const receive = (event: MessageEvent) => {
          if (event.source !== frame.current?.contentWindow || event.origin !== origin || event.data?.id !== requestId) return;
          if (event.data.result?.ready) { cleanup(); setReadyToken(result.token); setSetupStage(""); resolve(); }
        };
        const poll = setInterval(() => {
          if (sequence !== navigation.current) { cleanup(); reject(new Error("Notebook selection changed.")); return; }
          frame.current?.contentWindow?.postMessage({ type: "vercel-notebook-capabilities", id: requestId, token: result.token }, origin);
        }, 250);
        const timeout = setTimeout(() => { cleanup(); reject(new Error("The editor is still loading. Try the request again shortly.")); }, 60000);
        window.addEventListener("message", receive);
      });
    } finally {
      if (sequence === navigation.current) setSetupStarted(null);
    }
  }

  useEffect(() => {
    if (!pendingDrafts) return;
    const timer = setInterval(() => {
      for (const id of draftQueue.current.keys()) void flushDraft(id).catch(() => {});
    }, 5000);
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => { clearInterval(timer); window.removeEventListener("beforeunload", warn); };
  }, [pendingDrafts]);

  useEffect(() => {
    if (!activeEditor || busy || setupStarted !== null) return;
    let cancelled = false;
    const sequence = navigation.current;
    const check = async () => {
      try {
        const response = await fetch(`/api/notebooks/${activeEditor.notebookId}/editor-status`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: activeEditor.token }),
        });
        if (response.status !== 410 || cancelled || recoveries.current.has(activeEditor.token)) return;
        recoveries.current.add(activeEditor.token);
        setError("");
        setSetupStage("Recovering your Python environment…");
        await leaveEditor();
        if (sequence === navigation.current && selectedRef.current === activeEditor.notebookId) await openEditor(activeEditor.notebookId!, sequence);
      } catch (error) {
        recoveries.current.delete(activeEditor.token);
        if (sequence === navigation.current) setError(error instanceof Error ? error.message : "Automatic editor recovery failed.");
      }
    };
    const timer = setInterval(() => { void check(); }, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [activeEditor, busy, setupStarted]);

  useEffect(() => {
    if (!activeEditor || !editorReady) return;
    const interval = setInterval(() => {
      if (saving.current || closingRef.current) return;
      persist().catch((e) => setError(e.message));
    }, 30000);
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", unload);
    return () => {
      clearInterval(interval);
      window.removeEventListener("beforeunload", unload);
    };
  }, [activeEditor, editorReady, persist]);

  async function action(label: string, operation: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await operation();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }
  async function choose(id: string | null) {
    if (chatBusy || closingRef.current || id === selected) return;
    const editing = !!editor || setupStarted !== null;
    const outgoingId = editor?.notebookId;
    const sequence = ++navigation.current;
    if (id === null) await leaveEditor();
    selectedRef.current = id;
    setSelected(id); setMobile(false); setError(""); setSetupStage(""); setSetupStarted(null);
    let exported = false;
    try {
      // Selection changes immediately; retain the old iframe only until its memory is exported.
      await leaveEditor();
      exported = true;
      if (id && editing && sequence === navigation.current) await openEditor(id, sequence);
    } catch (error) {
      if (sequence !== navigation.current) return;
      setError(error instanceof Error ? error.message : "Could not switch notebooks.");
      if (!exported && editor && outgoingId) { selectedRef.current = outgoingId; setSelected(outgoingId); }
    }
  }
  const date = notebook
    ? new Date(notebook.updated_at * 1000).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "";
  return (
    <div className="app">
      {mobile && (
        <button
          className="scrim"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={mobile ? "sidebar open" : "sidebar"}>
        <div className="brand-row">
          <a
            className="brand"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              void choose(null);
            }}
          >
            <span className="brand-icon">
              <BookOpen size={19} />
            </span>
            <span>
              notebook<span className="brand-light">factory</span>
            </span>
          </a>
          <a
            className="repository-link"
            href="https://github.com/1st1/notebook-factory"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="View Notebook Factory on GitHub"
            title="View on GitHub"
          >
            <Github size={15} aria-hidden="true" />
          </a>
        </div>
        <button
          className="new-button"
          title={
            auth.user && !auth.can_edit
              ? "Only 1st1 can create notebooks"
              : undefined
          }
          disabled={!!busy || !!editor || (!!auth.user && !auth.can_edit)}
          onClick={() =>
            auth.can_edit
              ? setCreating(true)
              : location.assign("/api/auth/login")
          }
        >
          <Plus size={17} /> New notebook <span>+</span>
        </button>
        <div className="search">
          <Search size={15} />
          <input
            aria-label="Search notebooks"
            placeholder="Find a notebook…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span>/</span>
        </div>
        <div className="list-label">
          NOTEBOOKS <span>{notebooks.length.toString().padStart(2, "0")}</span>
        </div>
        <nav aria-label="Notebooks">
          {notebooks
            .filter((n) => n.title.toLowerCase().includes(query.toLowerCase()))
            .map((n) => (
              <button
                key={n.id}
                className={
                  "notebook-link " + (n.id === selected ? "active" : "")
                }
                disabled={!!busy || chatBusy}
                onClick={() => choose(n.id)}
              >
                <BookOpen size={16} />
                <span>{n.title}</span>
                {n.id === selected && <span className="active-dot" />}
              </button>
            ))}
          {!loading && !notebooks.length && (
            <p className="list-empty">A little space for your next big idea.</p>
          )}
          {query &&
            !notebooks.some((n) =>
              n.title.toLowerCase().includes(query.toLowerCase()),
            ) && <p className="list-empty">No matching notebooks.</p>}
        </nav>
        <div className="sidebar-bottom">
          {auth.user ? (
            <div className="account">
              <span className="avatar" aria-hidden="true">
                {auth.user.login[0].toUpperCase()}
                {auth.user.avatar_url && <img
                  key={auth.user.avatar_url}
                  src={auth.user.avatar_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  onError={event => { event.currentTarget.style.display = "none"; }}
                />}
              </span>
              <span>
                <strong>{auth.user.login}</strong>
                <small>{auth.can_edit ? "Workspace owner" : "Reader"}</small>
              </span>
              <form action="/api/auth/logout" method="post">
                <button
                  className="icon-button"
                  title="Sign out"
                  disabled={!!editor}
                >
                  <LogOut size={16} />
                </button>
              </form>
            </div>
          ) : (
            <a className="login" href="/api/auth/login">
              <Github size={17} /> Sign in with GitHub{" "}
              <ArrowUpRight size={15} />
            </a>
          )}
        </div>
      </aside>
      <main>
        <button
          className="icon-button mobile-toggle"
          aria-label="Open navigation"
          onClick={() => setMobile(true)}
        >
          <Menu size={19} />
        </button>
        {loading ? (
          <div className="empty">
            <LoaderCircle className="spin" />
            <p>Opening your workspace…</p>
          </div>
        ) : notebook ? (
          <>
            <section className="notebook-heading">
              <div className="title-row">
                <h1>{notebook.title}</h1>
                <div className="actions">
                  <a
                    className="button download"
                    aria-label="Download notebook"
                    title="Download .ipynb"
                    href={`/api/notebooks/${selected}/download`}
                  >
                    <Download size={16} />
                  </a>
                  {auth.can_edit && (
                    <button
                      className="button delete-notebook"
                      aria-label="Delete notebook"
                      title="Delete notebook"
                      disabled={!!busy || chatBusy}
                      onClick={() => {
                        if (!window.confirm(`Delete “${notebook.title}”? This permanently deletes its published notebook, draft, and chat history.`)) return;
                        void action("Deleting notebook…", async () => {
                          await api(`/notebooks/${notebook.id}/delete`, {});
                          setEditor(null);
                          setSelected(null);
                          setSaved("");
                          setNotebooks(items => {
                            const remaining = items.filter(item => item.id !== notebook.id);
                            try { sessionStorage.setItem(WORKSPACE_CACHE, JSON.stringify({ saved: Date.now(), notebooks: remaining })); } catch { /* Storage is optional. */ }
                            return remaining;
                          });
                          await refresh();
                        });
                      }}
                    ><Trash2 size={16} strokeWidth={1.5} /></button>
                  )}
                  {auth.can_edit && <button className="button" aria-expanded={chatOpen} onClick={() => setChatOpen(value => !value)}><MessageSquare size={16}/>Chat</button>}
                  {auth.can_edit && (!activeEditor ? (
                    <button className="button primary" disabled={!!busy || setupStarted !== null} onClick={() => { void openEditor(selected!).catch(e => setError(e.message)); }}>
                      <Pencil size={15} /> Edit notebook
                    </button>
                  ) : (
                    <button className="button primary" disabled={!!busy || chatBusy || !editorReady} onClick={() => action("Saving and closing…", () => persist(true, true))}>
                      <ArrowUpRight size={16} /> Save &amp; exit
                    </button>
                  ))}
                </div>
              </div>
              <div className="metadata">
                <span className="python-dot" /> Python 3 <span>·</span> Updated{" "}
                {date}
                <span>·</span>
                {activeEditor
                  ? saved || "Drafts autosave every 30 seconds"
                  : `Revision ${notebook.revision}`}
              </div>
            </section>
            {busy && !setupStage && (
              <div className="progress" role="status">
                <LoaderCircle size={16} className="spin" />
                {busy}
                {busy.startsWith("Starting") && (
                  <small>First startup can take a few minutes.</small>
                )}
              </div>
            )}
            {setupStage && (
              <section className="setup-progress" aria-label="Environment setup">
                <div className="progress" role="status">
                  {setupStarted !== null && <LoaderCircle size={16} className="spin" />}
                  <span>{setupStarted !== null ? setupStage : "Setup did not finish"}</span>
                  <small>{setupSeconds}s elapsed</small>
                </div>
                {setupLog && <pre ref={setupOutput} className="setup-output" aria-label="Installation output">{setupLog}</pre>}
              </section>
            )}
            <div className="notebook-workspace">
            <div className={"notebook-surface " + (activeEditor ? "editing" : "")}>
              <div className="surface-toolbar">
                <span>
                  <span className={activeEditor ? "green-dot" : "gray-dot"} />
                  {activeEditor ? "JUPYTER LAB" : "NOTEBOOK"}
                </span>
                <span>
                  {activeEditor ? (
                    "Changes are private until published"
                  ) : (
                    <>
                      <Check size={13} /> Published
                    </>
                  )}
                </span>
              </div>
              {editor && <iframe
                key={editor.url} ref={frame} title="Jupyter notebook editor" src={editor.url}
                style={editorReady ? undefined : { display: "none" }} referrerPolicy="no-referrer"
                allow="clipboard-read; clipboard-write"
              />}
              {!editorReady && <PublishedNotebook
                key={`${selected}-${renderVersion}-${notebook.render_url || "local"}`}
                notebook={notebook} version={renderVersion}
              />}
            </div>
            {auth.can_edit && <Suspense fallback={null}><Chat model={auth.chat_model} key={selected!} notebookId={selected!} editor={activeEditor} frame={frame} disabled={!!busy} open={chatOpen} onClose={() => setChatOpen(false)} onBusy={setChatBusy} onRename={renameNotebook} onEnterEditing={() => openEditor(selected!, navigation.current)} /></Suspense>}
            </div>
          </>
        ) : notebooks.length > 0 ? (
          <section className="empty welcome" aria-labelledby="welcome-title">
            <div className="welcome-art" aria-hidden="true">
              <div className="welcome-page welcome-page-back" />
              <div className="welcome-page welcome-page-front"><BookOpen size={32} strokeWidth={1.25} /><span /><span /><span /></div>
            </div>
            <div className="eyebrow">YOUR WORKSPACE</div>
            <h1 id="welcome-title">Choose a notebook.</h1>
            <p>Open a notebook from the sidebar<br />to explore its code, charts, and ideas.</p>
            <button className="button welcome-browse" onClick={() => setMobile(true)}><Menu size={16} /> Browse notebooks</button>
            <div className="welcome-hint"><span />{notebooks.length} {notebooks.length === 1 ? "notebook" : "notebooks"} to explore</div>
          </section>
        ) : (
          <div className="empty">
            <div className="empty-art">
              <BookOpen size={38} strokeWidth={1} />
            </div>
            <div className="eyebrow">A FRESH PAGE</div>
            <h1>Good ideas start here.</h1>
            <p>
              A home for experiments, discoveries, and Python notebooks.
              <br />
              Create a notebook, follow your curiosity, share what you find.
            </p>
            <button
              className="button primary"
              onClick={() =>
                auth.can_edit
                  ? setCreating(true)
                  : location.assign("/api/auth/login")
              }
            >
              <Plus size={16} />
              {auth.can_edit
                ? "Create your first notebook"
                : "Sign in to get started"}
            </button>
            {!auth.can_edit && (
              <small>
                Everyone can read. The workspace owner can create and edit.
              </small>
            )}
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
      </main>
      {creating && (
        <div
          className="modal-backdrop"
          onClick={() => !busy && setCreating(false)}
        >
          <form
            className="modal"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              action("Creating notebook…", async () => {
                const item = await api<Notebook>("/notebooks", { title });
                await refresh();
                setSelected(item.id);
                setCreating(false);
                setTitle("");
              });
            }}
          >
            <div className="eyebrow">SOMETHING NEW</div>
            <h2>Give your idea a name.</h2>
            <label htmlFor="title">Notebook title</label>
            <input
              id="title"
              autoFocus
              required
              maxLength={120}
              placeholder="An interesting experiment"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <div className="modal-actions">
              <button
                type="button"
                className="button"
                onClick={() => setCreating(false)}
                disabled={!!busy || chatBusy}
              >
                Cancel
              </button>
              <button
                className="button primary"
                disabled={!!busy || !title.trim()}
              >
                {busy ? "Creating…" : "Create notebook"}
                <Plus size={16} />
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
