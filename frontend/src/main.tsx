import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  Code2,
  Download,
  Github,
  LoaderCircle,
  LogOut,
  Menu,
  Pencil,
  Plus,
  Search,
  X,
} from "lucide-react";
import "./style.css";

type Notebook = {
  id: string;
  title: string;
  updated_at: number;
  revision: number;
};
type Auth = {
  user: { login: string } | null;
  can_edit: boolean;
  configured: boolean;
};
type Editor = { name: string; url: string; token: string };
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    "/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
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

function App() {
  const [auth, setAuth] = useState<Auth>({
    user: null,
    can_edit: false,
    configured: false,
  });
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selected, setSelected] = useState<string | null>(
    new URLSearchParams(location.search).get("notebook"),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [saved, setSaved] = useState("");
  const [mobile, setMobile] = useState(false);
  const [renderVersion, setRenderVersion] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const saving = useRef(false);
  const notebook = notebooks.find((n) => n.id === selected);

  const refresh = useCallback(async () => {
    const [list, identity] = await Promise.all([
      api<Notebook[]>("/notebooks"),
      api<Auth>("/auth/me"),
    ]);
    setNotebooks(list);
    setAuth(identity);
    setSelected((current) =>
      list.some((n) => n.id === current) ? current : list[0]?.id || null,
    );
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
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        cleanup();
        reject(
          new Error(
            "Jupyter did not finish saving. Wait for it to load and retry.",
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
          resolve();
        }
        if (event.data.type === "vercel-notebook-save-error") {
          cleanup();
          reject(new Error(event.data.message));
        }
      };
      window.addEventListener("message", receive);
      target.postMessage(
        { type: "vercel-notebook-save", id, token: editor.token },
        origin,
      );
    });
  }, [editor]);

  const persist = useCallback(
    async (publish = false, close = false) => {
      if (!editor || !selected) return;
      while (saving.current)
        await new Promise((resolve) => setTimeout(resolve, 100));
      saving.current = true;
      try {
        await saveBridge();
        await api(`/notebooks/${selected}/${close ? "close" : "save"}`, {
          token: editor.token,
          publish,
        });
        setSaved(
          "Draft saved at " +
            new Date().toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            }),
        );
        if (publish) {
          setRenderVersion((v) => v + 1);
          await refresh();
        }
        if (close) {
          setEditor(null);
          setSaved("");
        }
      } finally {
        saving.current = false;
      }
    },
    [editor, selected, saveBridge, refresh],
  );

  useEffect(() => {
    if (!editor) return;
    const interval = setInterval(() => {
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
  }, [editor, persist]);

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
  async function choose(id: string) {
    if (busy || saving.current || id === selected) return;
    await action("Opening notebook", async () => {
      if (editor) await persist(false, true);
      setSelected(id);
      setMobile(false);
    });
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
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            if (editor) e.preventDefault();
          }}
        >
          <span className="brand-icon">
            <BookOpen size={19} />
          </span>
          <span>
            notebook<span className="brand-light">factory</span>
          </span>
        </a>
        <div className="workspace-label">YOUR CORNER OF CURIOSITY</div>
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
                disabled={!!busy}
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
          <div className="public-note">
            <span className="green-dot" /> Open notebooks. Shared ideas.
          </div>
          {auth.user ? (
            <div className="account">
              <span className="avatar">{auth.user.login[0].toUpperCase()}</span>
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
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-toggle"
              aria-label="Open navigation"
              onClick={() => setMobile(true)}
            >
              <Menu size={19} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{notebook?.title || "Notebooks"}</strong>
          </div>
          <span className="view-label">
            <span className={editor ? "green-dot" : "gray-dot"} />
            {editor ? "Live editor" : "Public view"}
          </span>
        </header>
        {error && (
          <div className="error" role="alert">
            <span>{error}</span>
            {editor && (
              <button
                disabled={!!busy}
                onClick={() =>
                  action("Reconnecting…", async () => {
                    setEditor(
                      await api<Editor>(`/notebooks/${selected}/editor`, {}),
                    );
                  })
                }
              >
                Reconnect editor
              </button>
            )}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {loading ? (
          <div className="empty">
            <LoaderCircle className="spin" />
            <p>Opening your workspace…</p>
          </div>
        ) : notebook ? (
          <>
            <section className="notebook-heading">
              <div className="eyebrow">
                <Code2 size={14} /> PYTHON NOTEBOOK
              </div>
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
                  {auth.can_edit &&
                    (!editor ? (
                      <button
                        className="button primary"
                        disabled={!!busy}
                        onClick={() =>
                          action(
                            "Starting your Python environment…",
                            async () => {
                              setEditor(
                                await api<Editor>(
                                  `/notebooks/${selected}/editor`,
                                  {},
                                ),
                              );
                            },
                          )
                        }
                      >
                        <Pencil size={15} /> Edit notebook
                      </button>
                    ) : (
                      <>
                        <button
                          className="button"
                          disabled={!!busy}
                          onClick={() =>
                            action("Saving and closing…", () =>
                              persist(false, true),
                            )
                          }
                        >
                          Close editor
                        </button>
                        <button
                          className="button primary"
                          disabled={!!busy}
                          onClick={() =>
                            action("Publishing…", () => persist(true))
                          }
                        >
                          <ArrowUpRight size={16} /> Publish
                        </button>
                      </>
                    ))}
                </div>
              </div>
              <div className="metadata">
                <span className="python-dot" /> Python 3 <span>·</span> Updated{" "}
                {date}
                <span>·</span>
                {editor
                  ? saved || "Drafts autosave every 30 seconds"
                  : `Revision ${notebook.revision}`}
              </div>
            </section>
            {busy && (
              <div className="progress" role="status">
                <LoaderCircle size={16} className="spin" />
                {busy}
                {busy.startsWith("Starting") && (
                  <small>First startup can take a few minutes.</small>
                )}
              </div>
            )}
            <div className={"notebook-surface " + (editor ? "editing" : "")}>
              <div className="surface-toolbar">
                <span>
                  <span className={editor ? "green-dot" : "gray-dot"} />
                  {editor ? "JUPYTER LAB" : "NOTEBOOK"}
                </span>
                <span>
                  {editor ? (
                    "Changes are private until published"
                  ) : (
                    <>
                      <Check size={13} /> Published
                    </>
                  )}
                </span>
              </div>
              {editor ? (
                <iframe
                  key={editor.url}
                  ref={frame}
                  title="Jupyter notebook editor"
                  src={editor.url}
                  referrerPolicy="no-referrer"
                  allow="clipboard-read; clipboard-write"
                />
              ) : (
                <iframe
                  key={`${selected}-${renderVersion}`}
                  title="Rendered notebook"
                  sandbox="allow-scripts allow-downloads"
                  src={`/api/notebooks/${selected}/render?v=${renderVersion}`}
                  referrerPolicy="no-referrer"
                />
              )}
            </div>
            <footer>
              <span>Made for thinking out loud.</span>
              <span>
                Notebook Factory <span className="footer-star">✳</span>
              </span>
            </footer>
          </>
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
                disabled={!!busy}
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
