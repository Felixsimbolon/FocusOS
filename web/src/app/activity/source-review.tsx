"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Source = {
  id: string; kind: string; title: string; normalized_body: string | null;
  received_at: string; body_expires_at: string;
};
type Extraction = {
  id: string; status: "processing" | "ready" | "failed"; safe_error: string | null;
  confirmed_item_keys: string[];
  validated_payload: {
    tasks: { local_ref: string; title: string; evidence: { quote: string }[] }[];
    facts: { text: string; evidence: { quote: string }[] }[];
    events: { title: string }[];
  } | null;
};
type Capture = {
  tasks_saved: number; memories_saved: number; task_failures: number;
  memory_failures: number; memory_ids: string[];
};
type Result = { extraction: Extraction; capture?: Capture };
type Memory = { id: string; source_id: string; text: string; evidence_quote: string; embedding_status: string };

async function json<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "Request failed");
  return data as T;
}

async function embed(ids: string[]) {
  for (const id of ids) {
    try { await fetch("/api/memories/" + id + "/embed", { method: "POST" }); }
    catch { /* Memory remains saved; embedding can be retried. */ }
  }
}

export function SourceReview() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState<Source | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useRef<{ key: string; payload: string } | null>(null);
  const attempted = useRef<Set<string>>(new Set());

  const select = useCallback(async (source: Source) => {
    setSelected(source); setExtraction(null);
    const [extractionResponse, memoryResponse] = await Promise.all([
      fetch("/api/sources/" + source.id + "/extraction", { cache: "no-store" }),
      fetch("/api/memories", { cache: "no-store" }),
    ]);
    let result = extractionResponse.ok ? (await extractionResponse.json() as Result).extraction : null;
    let sourceMemories = memoryResponse.ok
      ? (await memoryResponse.json() as { memories: Memory[] }).memories.filter((memory) => memory.source_id === source.id)
      : [];
    const incomplete = result?.status === "ready" && (
      result.confirmed_item_keys.length < (result.validated_payload?.tasks.length ?? 0) ||
      sourceMemories.length < (result.validated_payload?.facts.length ?? 0));
    if (incomplete && source.normalized_body && !attempted.current.has(source.id)) {
      attempted.current.add(source.id);
      const retryResponse = await fetch("/api/sources/" + source.id + "/extract", { method: "POST" });
      if (retryResponse.ok) {
        const retry = await retryResponse.json() as Result;
        await embed(retry.capture?.memory_ids ?? []);
        result = retry.extraction;
        const latest = await fetch("/api/memories", { cache: "no-store" });
        if (latest.ok) sourceMemories = (await latest.json() as { memories: Memory[] }).memories.filter((memory) => memory.source_id === source.id);
      }
    }
    setExtraction(result); setMemories(sourceMemories);
  }, []);

  const reload = useCallback(async () => {
    const data = await json<{ sources: Source[] }>(await fetch("/api/sources", { cache: "no-store" }));
    setSources(data.sources);
    const id = new URLSearchParams(window.location.search).get("source");
    if (id) {
      let source = data.sources.find((item) => item.id === id);
      if (!source) {
        const detail = await fetch("/api/sources/" + encodeURIComponent(id), { cache: "no-store" });
        if (detail.ok) {
          source = (await detail.json() as { source: Source }).source;
          setSources((current) => [source!, ...current.filter((item) => item.id !== id)]);
        }
      }
      if (source) await select(source);
    }
  }, [select]);

  useEffect(() => { void reload().catch(() => setMessage("Could not load sources.")); }, [reload]);
  useEffect(() => {
    const listener = () => { void reload().catch(() => setMessage("Could not refresh sources.")); };
    window.addEventListener("focusos:sources-changed", listener);
    return () => window.removeEventListener("focusos:sources-changed", listener);
  }, [reload]);

  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    const payload = JSON.stringify({ title: title.trim(), text: body });
    if (!pending.current || pending.current.payload !== payload) pending.current = { key: crypto.randomUUID(), payload };
    try {
      const data = await json<{ source: Source; extraction?: Result }>(await fetch("/api/sources/manual?background=true", {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": pending.current.key },
        body: payload,
      }));
      pending.current = null;
      setSources((current) => [data.source, ...current.filter((item) => item.id !== data.source.id)]);
      setBody(""); setTitle("");
      await select(data.source);
      setMessage(data.extraction?.extraction.status === "ready"
        ? "Source organized. Tasks and grounded memories were saved automatically."
        : "Source saved. Organization runs on the server; follow it in System.");
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save source"); }
    finally { setBusy(false); }
  }

  async function retry() {
    if (!selected) return;
    setBusy(true); setMessage("Processing source...");
    try {
      const data = await json<Result>(await fetch("/api/sources/" + selected.id + "/extract", { method: "POST" }));
      await embed(data.capture?.memory_ids ?? []);
      await select(selected);
      setMessage(data.extraction.status === "ready" ? "Source organized." :
        data.extraction.status === "failed" ? "Processing failed. Try again later." : "Processing is already running.");
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Processing unavailable"); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected || selected.kind !== "gmail" || !window.confirm("Remove this imported source and its linked FocusOS data?")) return;
    setBusy(true);
    try {
      await json(await fetch("/api/sources/" + selected.id, { method: "DELETE" }));
      setSources((current) => current.filter((item) => item.id !== selected.id));
      setSelected(null); setExtraction(null); setMemories([]);
      setMessage("Imported source removed.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not remove source"); }
    finally { setBusy(false); }
  }

  return <section className="source-review">
    <div className="activity-columns">
      <form className="task-form review-panel source-compose" onSubmit={(event) => void create(event)}>
        <div className="activity-panel-heading"><span className="activity-icon">＋</span><div><h2>Add a source</h2><p>Paste a message or brief. FocusOS finds tasks and sourced facts for you.</p></div></div>
        <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} placeholder="e.g. Project update" required /></label>
        <label>Content<textarea rows={7} value={body} onChange={(event) => setBody(event.target.value)} placeholder="Paste the source text here..." required /></label>
        <button type="submit" disabled={busy || !body.trim()}>{busy ? "Organizing..." : "Save and organize"}</button>
        <p className="activity-hint">Source text is kept for up to 30 days. Tasks and memories keep their source link.</p>
      </form>
      <div className="review-panel source-library">
        <div className="activity-panel-heading"><span className="activity-icon">◫</span><div><h2>Your sources</h2><p>{sources.length} saved {sources.length === 1 ? "source" : "sources"}</p></div></div>
        {sources.length === 0 ? <div className="activity-empty">No sources yet. Add a note or sync labeled Gmail to begin.</div> :
          <ul className="source-list">{sources.map((source) => <li key={source.id}>
            <button type="button" className={selected?.id === source.id ? "selected-source" : "secondary-button"}
              onClick={() => void select(source)}>
              <span>{source.title}</span><small>{source.kind === "gmail" ? "Gmail" : source.kind === "task" ? "Manual task" : "Manual"} · {new Date(source.received_at).toLocaleDateString()}</small>
            </button>
          </li>)}</ul>}
      </div>
    </div>
    {selected && <div className="review-panel source-detail">
      <div className="activity-panel-heading"><span className="activity-icon">✦</span><div><h2>{selected.title}</h2><p>{selected.kind === "gmail" ? "Gmail source" : selected.kind === "task" ? "Manual task source" : "Manual source"} · {new Date(selected.received_at).toLocaleString()}</p></div></div>
      {extraction?.status === "ready" && <div className="activity-result-banner">Organized automatically · {extraction.confirmed_item_keys.length} tasks · {memories.length} memories</div>}
      {extraction?.status === "processing" && <p role="status">Processing is in progress. Reload shortly to see the results.</p>}
      {extraction?.status === "failed" && <p role="alert">Processing failed ({extraction.safe_error ?? "unknown"}). Your source is saved.</p>}
      {(!extraction || extraction.status === "failed" || (extraction.status === "ready" && (
        extraction.confirmed_item_keys.length < (extraction.validated_payload?.tasks.length ?? 0) ||
        memories.length < (extraction.validated_payload?.facts.length ?? 0)))) && selected.normalized_body && selected.kind !== "task" && <button type="button" onClick={() => void retry()} disabled={busy}>Retry saving</button>}
      {extraction?.status === "ready" && extraction.validated_payload && <>
        <div className="activity-results-grid">
          <div><h3>Tasks</h3>{extraction.validated_payload.tasks.length === 0 ? <p>No tasks found.</p> :
            extraction.validated_payload.tasks.map((task) => <article className="activity-result" key={task.local_ref}><strong>{task.title}</strong><small>{extraction.confirmed_item_keys.includes(task.local_ref) ? "Saved to tasks" : "Save incomplete"}</small><blockquote>{task.evidence[0]?.quote}</blockquote></article>)}</div>
          <div><h3>Memories</h3>{memories.length === 0 ? <p>No sourced facts found.</p> :
            memories.map((memory) => <article className="activity-result" key={memory.id}><strong>{memory.text}</strong><small>{memory.embedding_status === "ready" ? "Searchable" : "Saved"}</small><blockquote>{memory.evidence_quote}</blockquote></article>)}</div>
        </div>
        {extraction.validated_payload.events.length > 0 && <p className="activity-hint">Calendar mentions were recognized; no event was created automatically.</p>}
      </>}
      {selected.kind === "task" && <div className="activity-results-grid">
        <div><h3>Memory from this task</h3>{memories.map(memory =>
          <article className="activity-result" key={memory.id}><strong>{memory.text}</strong>
            <small>{memory.embedding_status === "ready" ? "Searchable" : "Saved"}</small>
            <blockquote>{memory.evidence_quote}</blockquote></article>)}</div>
      </div>}      <details className="source-preview"><summary>View original source</summary><pre className="source-text">{selected.normalized_body ?? "Source text has expired."}</pre></details>
      {selected.kind === "gmail" && <button type="button" className="secondary-button" onClick={() => void remove()} disabled={busy}>Remove imported source</button>}
    </div>}
    {message && <p className="activity-message" role="status">{message}</p>}
  </section>;
}
