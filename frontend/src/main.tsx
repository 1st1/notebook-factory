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
type LiveEditor = Editor & { notebookId: string; ready: boolean; connected: boolean; expired?: boolean };
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

function ChatLoading({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <aside className="chat-panel" hidden={!open} aria-label="Notebook chat" aria-busy="true">
    <header className="surface-toolbar">
      <span><span className="green-dot" />NOTEBOOK CHAT</span>
      <span className="chat-header-actions"><button className="icon-button" aria-label="Close chat" onClick={onClose}><X size={18} /></button></span>
    </header>
    <div className="chat-messages"><p className="chat-hint chat-status" role="status"><LoaderCircle size={14} className="spin" aria-hidden="true" />Loading conversation…</p></div>
    <form><textarea aria-label="Message" placeholder="Loading conversation…" disabled rows={3} /></form>
  </aside>;
}

function App() {
  const [auth, setAuth] = useState<Auth>({
    user: null,
    can_edit: false,
    configured: false,
  });
  const [authLoaded, setAuthLoaded] = useState(false);
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
  const [editors, setEditors] = useState<Record<string, LiveEditor>>({});
  const editorsRef = useRef(editors);
  const editor = selected ? editors[selected] ?? null : null;
  const [chatPanel, setChatPanel] = useState<{ id: string | null; open: boolean }>({ id: null, open: false });
  const chatOpen = chatPanel.id === selected ? chatPanel.open : true;
  const setChatOpen = (open: boolean) => setChatPanel({ id: selected, open });
  const [chatStates, setChatStates] = useState<Record<string, { busy: boolean; working: boolean }>>({});
  const chatBusy = !!selected && !!chatStates[selected]?.busy;
  const [visitedChats, setVisitedChats] = useState<string[]>([]);
  const chatIds = [...new Set([...visitedChats, ...(selected ? [selected] : [])])].filter(id => notebooks.some(n => n.id === id));
  useEffect(() => { if (selected) setVisitedChats(ids => ids.includes(selected) ? ids : [...ids, selected]); }, [selected]);
  const reportChatBusy = useCallback((id: string, busy: boolean, working: boolean) => {
    setChatStates(states => ({ ...states, [id]: { busy, working } }));
  }, []);
  const startingEditors = useRef(new Map<string, Promise<void>>());
  const [startingIds, setStartingIds] = useState<Set<string>>(new Set());
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const recoveries = useRef(new Set<string>());
  const savingEditors = useRef(new Map<string, Promise<void>>());
  const saveAgain = useRef(new Set<string>());
  const closingTokens = useRef(new Set<string>());
  const frames = useRef(new Map<string, HTMLIFrameElement>());
  const [saved, setSaved] = useState("");
  const [mobile, setMobile] = useState(false);
  const [renderVersion, setRenderVersion] = useState(0);
  const activeEditor = editor?.connected ? editor : null;
  const editorReady = !!activeEditor?.ready;
  const notebook = notebooks.find((n) => n.id === selected);

  function putEditor(id: string, value: LiveEditor | null) {
    const next = { ...editorsRef.current };
    if (value) next[id] = value;
    else delete next[id];
    editorsRef.current = next;
    setEditors(next);
  }

  function patchEditor(id: string, token: string, patch: Partial<LiveEditor>) {
    const current = editorsRef.current[id];
    if (current?.token === token) putEditor(id, { ...current, ...patch });
  }

  const saveAfterTurn = useCallback((id: string) => {
    const current = editorsRef.current[id];
    if (current) void saveEditor(current).catch(() => setError("Notebook could not be saved. Autosave will retry."));
  }, []);

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
      api<Auth>("/auth/me").then(setAuth).finally(() => setAuthLoaded(true)),
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

  const saveBridge = useCallback(async (current: Editor) => {
    if (!frames.current.get(current.token)?.contentWindow)
      throw new Error("The editor is not ready yet.");
    const target = frames.current.get(current.token)!.contentWindow!;
    const origin = new URL(current.url).origin;
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
        { type: "vercel-notebook-export", id, token: current.token },
        origin,
      );
    });
  }, []);

  function saveEditor(current: LiveEditor): Promise<void> {
    if (!current.ready || closingTokens.current.has(current.token)) return Promise.resolve();
    const existing = savingEditors.current.get(current.token);
    if (existing) { saveAgain.current.add(current.token); return existing; }
    const work = (async () => {
      do {
        saveAgain.current.delete(current.token);
        const source = await saveBridge(current);
        if (closingTokens.current.has(current.token) || editorsRef.current[current.notebookId]?.token !== current.token) return;
        const result = await api<{ changed: boolean; render_url?: string | null; revision: number; updated_at: number }>(
          `/notebooks/${current.notebookId}/save`, { token: current.token, source, publish: true }, AbortSignal.timeout(60000),
        );
        if (result.changed) {
          setNotebooks(items => {
            const updated = items.map(item => item.id === current.notebookId ? { ...item, render_url: result.render_url, revision: result.revision, updated_at: result.updated_at } : item);
            try { sessionStorage.setItem(WORKSPACE_CACHE, JSON.stringify({ saved: Date.now(), notebooks: updated })); } catch { /* Storage is optional. */ }
            return updated;
          });
          if (selectedRef.current === current.notebookId) setRenderVersion(value => value + 1);
        }
        if (selectedRef.current === current.notebookId) setSaved("Saved at " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
      } while (saveAgain.current.has(current.token));
    })().catch(error => {
      if (closingTokens.current.has(current.token) || editorsRef.current[current.notebookId]?.token !== current.token) return;
      throw error;
    }).finally(() => savingEditors.current.delete(current.token));
    savingEditors.current.set(current.token, work);
    return work;
  }

  function openEditor(id: string): Promise<void> {
    const existing = startingEditors.current.get(id);
    if (existing) return existing;
    if (editorsRef.current[id]?.connected && editorsRef.current[id]?.ready) return Promise.resolve();
    setStartingIds(ids => new Set(ids).add(id));
    const promise = loadEditor(id).finally(() => {
      startingEditors.current.delete(id);
      setStartingIds(ids => { const next = new Set(ids); next.delete(id); return next; });
    });
    startingEditors.current.set(id, promise);
    return promise;
  }

  async function loadEditor(id: string) {
    const visible = () => selectedRef.current === id;
    if (visible()) { setSetupStage("Connecting…"); setSetupLog(""); setSetupSeconds(0); setSetupStarted(Date.now()); }
    const previous = editorsRef.current[id];
    try {
      if (previous?.ready) {
        closingTokens.current.add(previous.token);
        const source = await saveBridge(previous);
        await api(`/notebooks/${id}/close`, { token: previous.token, source, publish: false });
      }
      const result = await startEditor(id, (kind, message) => {
        if (!visible()) return;
        if (kind === "progress") setSetupStage(message);
        if (kind === "log") setSetupLog(log => (log + message).slice(-20000));
      });
      putEditor(id, { ...result, notebookId: id, ready: false, connected: false });
      if (visible()) setSetupStage("Loading notebook…");
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      await new Promise<void>((resolve, reject) => {
        const requestId = crypto.randomUUID();
        const origin = new URL(result.url).origin;
        const cleanup = () => { clearInterval(poll); clearTimeout(timeout); window.removeEventListener("message", receive); };
        const receive = (event: MessageEvent) => {
          if (event.source !== frames.current.get(result.token)?.contentWindow || event.origin !== origin || event.data?.id !== requestId) return;
          if (event.data.result?.ready && event.data.result?.connected !== false) {
            cleanup(); patchEditor(id, result.token, { ready: true, connected: true });
            if (visible()) setSetupStage("");
            resolve();
          }
        };
        const poll = setInterval(() => {
          frames.current.get(result.token)?.contentWindow?.postMessage({ type: "vercel-notebook-capabilities", id: requestId, token: result.token }, origin);
        }, 250);
        const timeout = setTimeout(() => { cleanup(); reject(new Error("The editor is still loading. Try the request again shortly.")); }, 60000);
        window.addEventListener("message", receive);
      });
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    } finally {
      if (previous) closingTokens.current.delete(previous.token);
      if (visible()) setSetupStarted(null);
    }
  }

  function editorConnected(current: LiveEditor): Promise<boolean> {
    const target = frames.current.get(current.token)?.contentWindow;
    if (!target) return Promise.resolve(false);
    const origin = new URL(current.url).origin;
    const id = crypto.randomUUID();
    return new Promise(resolve => {
      const finish = (connected: boolean) => { clearTimeout(timer); window.removeEventListener("message", receive); resolve(connected); };
      const receive = (event: MessageEvent) => {
        if (event.source === target && event.origin === origin && event.data?.id === id && event.data.type === "vercel-notebook-tool-result") {
          finish(!!event.data.result?.ready && event.data.result?.connected !== false);
        }
      };
      const timer = setTimeout(() => finish(false), 5000);
      window.addEventListener("message", receive);
      target.postMessage({ type: "vercel-notebook-capabilities", id, token: current.token }, origin);
    });
  }

  useEffect(() => {
    let cancelled = false;
    let checking = false;
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        await Promise.all(Object.values(editorsRef.current).filter(current => current.ready).map(async current => {
          if (closingTokens.current.has(current.token)) return;
          try {
            const [response, connected] = await Promise.all([fetch(`/api/notebooks/${current.notebookId}/editor-status`, {
              method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: current.token }), signal: AbortSignal.timeout(5000),
            }), editorConnected(current)]);
            if (cancelled || closingTokens.current.has(current.token) || editorsRef.current[current.notebookId]?.token !== current.token) return;
            patchEditor(current.notebookId, current.token, { connected: response.ok && connected, expired: response.status === 410 || response.status === 409 });
            // Background editors stay disconnected; only recover the currently displayed one.
            if (response.status === 410 && current.connected && selectedRef.current === current.notebookId && !recoveries.current.has(current.token)) {
              recoveries.current.add(current.token);
              try { await openEditor(current.notebookId); }
              catch (error) { setError(error instanceof Error ? error.message : "Automatic editor recovery failed."); }
              finally { recoveries.current.delete(current.token); }
            }
          } catch {
            if (!cancelled) patchEditor(current.notebookId, current.token, { connected: false });
          }
        }));
      } finally { checking = false; }
    };
    const timer = setInterval(() => { void check(); }, 15000);
    const online = () => { void check(); };
    const offline = () => {
      for (const current of Object.values(editorsRef.current)) patchEditor(current.notebookId, current.token, { connected: false });
    };
    window.addEventListener("online", online); window.addEventListener("offline", offline);
    return () => { cancelled = true; clearInterval(timer); window.removeEventListener("online", online); window.removeEventListener("offline", offline); };
  }, []);

  useEffect(() => {
    const saveAll = () => {
      for (const current of Object.values(editorsRef.current)) {
        void saveEditor(current).catch(() => setError("A notebook could not be saved. Keep this tab open; autosave will retry."));
      }
    };
    const interval = setInterval(saveAll, 30000);
    const hidden = () => { if (document.visibilityState === "hidden") saveAll(); };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("blur", saveAll);
    const unload = (event: BeforeUnloadEvent) => {
      if (Object.keys(editorsRef.current).length) event.preventDefault();
    };
    window.addEventListener("beforeunload", unload);
    return () => { clearInterval(interval); window.removeEventListener("beforeunload", unload); document.removeEventListener("visibilitychange", hidden); window.removeEventListener("blur", saveAll); };
  }, []);

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
  function choose(id: string | null) {
    if (id === selected) return;
    setChatPanel({ id, open: true });
    if (editor?.ready) void saveEditor(editor).catch(() => setError("A notebook draft could not be saved. Keep this tab open; autosave will retry."));
    selectedRef.current = id;
    setSelected(id); setMobile(false); setError(""); setSaved("");
    const loadingEditor = !!id && startingEditors.current.has(id);
    setSetupStage(loadingEditor ? "Loading notebook…" : "");
    setSetupStarted(loadingEditor ? Date.now() : null);
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
          disabled={!!busy || (!!auth.user && !auth.can_edit)}
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
                disabled={!!busy}
                onClick={() => choose(n.id)}
              >
                <BookOpen size={16} />
                <span>{n.title}</span>
                {startingIds.has(n.id) ? <span className="running-editor-dot starting-editor-dot" aria-label="Editor starting" title="Starting Python environment…" /> : chatStates[n.id]?.working ? <span className="agent-working-dots" aria-label="Agent working" title="Agent working"><i /><i /><i /></span> : editors[n.id]?.ready && editors[n.id]?.connected && <span className="running-editor-dot" aria-label="Editor connected" title="Editor running" />}
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
                  disabled={Object.keys(editors).length > 0 || Object.values(chatStates).some(state => state.busy)}
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
                          putEditor(notebook.id, null);
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
                  {auth.can_edit && <button className="button" aria-expanded={chatOpen} onClick={() => setChatOpen(!chatOpen)}><MessageSquare size={16}/>Chat</button>}
                  {auth.can_edit && !activeEditor && (
                    <button className="button primary" disabled={!!busy || setupStarted !== null} onClick={() => { void openEditor(selected!).catch(e => setError(e.message)); }}>
                      <Pencil size={15} /> Edit notebook
                    </button>
                  )}
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
            <div className="notebook-workspace" style={notebook ? undefined : { display: "none" }}>
            <div className={"notebook-surface " + (activeEditor ? "editing" : "")}>
              <div className="surface-toolbar">
                <span>
                  <span className={activeEditor ? "green-dot" : "gray-dot"} />
                  {activeEditor ? "JUPYTER LAB" : "NOTEBOOK"}
                </span>
                <span>
                  {activeEditor ? (
                    "Changes save automatically"
                  ) : (
                    <>
                      <Check size={13} /> Published
                    </>
                  )}
                </span>
              </div>
              {Object.values(editors).map(current => <iframe
                key={current.token} ref={node => {
                  if (node) frames.current.set(current.token, node); else frames.current.delete(current.token);
                }} title={`Jupyter editor: ${notebooks.find(item => item.id === current.notebookId)?.title || current.notebookId}`} src={current.url}
                style={editorReady && current.notebookId === selected ? undefined : { display: "none" }} referrerPolicy="no-referrer"
                allow="clipboard-read; clipboard-write"
              />)}
              {notebook && !editorReady && <PublishedNotebook
                key={`${selected}-${renderVersion}-${notebook.render_url || "local"}`}
                notebook={notebook} version={renderVersion}
              />}
            </div>
            {notebook && !authLoaded && <ChatLoading open={chatOpen} onClose={() => setChatOpen(false)} />}
            {auth.can_edit && chatIds.map(id => <Suspense key={id} fallback={<ChatLoading open={selected === id && chatOpen} onClose={() => setChatPanel({ id, open: false })} />}><Chat
              model={auth.chat_model} notebookId={id} editorStarting={startingIds.has(id)}
              editor={editors[id]?.connected ? editors[id] : null}
              getFrame={() => { const current = editorsRef.current[id]; return current ? frames.current.get(current.token) ?? null : null; }}
              disabled={selected === id && !!busy} open={selected === id && chatOpen}
              onClose={() => setChatPanel({ id, open: false })} onTurnFinished={saveAfterTurn}
              onBusy={reportChatBusy} onRename={renameNotebook} onEnterEditing={() => openEditor(id)}
            /></Suspense>)}
            </div>
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
