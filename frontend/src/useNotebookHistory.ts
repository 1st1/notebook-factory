import { useEffect, useMemo, useRef, useState } from "react";
import type { UIMessage } from "ai";

export function useNotebookHistory(notebookId: string, token: string | null, messages: UIMessage[], setMessages: (messages: UIMessage[]) => void, busy: boolean) {
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("[]");
  const [error, setError] = useState("");
  const [reloadRequired, setReloadRequired] = useState(false);
  const [reload, setReload] = useState(0);
  const revision = useRef(0);
  const inFlight = useRef(false);
  const active = useRef(true);
  const serialized = useMemo(() => JSON.stringify(messages), [messages]);
  const dirty = loaded && serialized !== saved;
  const endpoint = `/api/notebooks/${notebookId}/chat-history`;

  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    setLoading(true);
    setLoaded(false);
    setError("");
    fetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }), signal: controller.signal,
    }).then(async response => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Could not load chat history.");
      if (controller.signal.aborted) return;
      revision.current = body.revision;
      setSaved(JSON.stringify(body.messages));
      setMessages(body.messages);
      setLoaded(true);
      setReloadRequired(false);
    }).catch(error => {
      if (!controller.signal.aborted) setError(error.message);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => { active.current = false; controller.abort(); };
  }, [endpoint, token, reload, setMessages]);

  useEffect(() => {
    if (!loaded || busy || !dirty || error || inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    const snapshot = serialized;
    fetch(endpoint, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, revision: revision.current, messages: JSON.parse(snapshot) }),
    }).then(async response => {
      const body = await response.json();
      if (!response.ok) {
        if (response.status === 409 && active.current) setReloadRequired(true);
        throw new Error(body.detail || "Could not save chat history.");
      }
      if (active.current) { revision.current = body.revision; setSaved(snapshot); }
    }).catch(error => {
      if (active.current) setError(error.message);
    }).finally(() => {
      inFlight.current = false;
      if (active.current) setSaving(false);
    });
  }, [loaded, busy, dirty, error, serialized, endpoint, token, saving]);

  return {
    loaded, loading, saving, error,
    blocking: loading || saving || (dirty && !error),
    // Reading history must not lock navigation; pending writes still protect the conversation.
    navigationBlocking: saving || (dirty && !error),
    reloadRequired,
    clearError: () => setError(""),
    retry: () => {
      if (!loaded || reloadRequired) setReload(value => value + 1);
      else setError("");
    },
  };
}
