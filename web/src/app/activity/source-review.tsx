"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { queueJob, type Job } from "../jobs/client";
import { activeOrganization, followOrganization, organizationMessage } from "../organization";

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

export function SourceReview() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState<Source | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  const selectedRef = useRef<Source | null>(null);

  const select = useCallback(async (source: Source) => {
    selectedRef.current = source;
    setSelected(source); setExtraction(null);
    const [extractionResponse, memoryResponse] = await Promise.all([
      fetch("/api/sources/" + source.id + "/extraction", { cache: "no-store" }),
      fetch("/api/memories?source_id=" + source.id, { cache: "no-store" }),
    ]);
    const result = extractionResponse.ok ? (await extractionResponse.json() as Result).extraction : null;
    const sourceMemories = memoryResponse.ok
      ? (await memoryResponse.json() as { memories: Memory[] }).memories.filter((memory) => memory.source_id === source.id)
      : [];
    if (selectedRef.current?.id === source.id) { setExtraction(result); setMemories(sourceMemories); }
  }, []);

  const reload = useCallback(async (preferredId?: string) => {
    const data = await json<{ sources: Source[] }>(await fetch("/api/sources", { cache: "no-store" }));
    setSources(data.sources.filter(source => source.kind !== "task"));
    const id = preferredId ?? selectedRef.current?.id ?? new URLSearchParams(window.location.search).get("source") ?? data.sources[0]?.id;
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

  const observe = useCallback(async (job: Job, sourceId: string, signal: AbortSignal) => {
    setBusy(true);
    try {
      const finished = await followOrganization(job, current => setMessage(organizationMessage(current)), signal);
      await reload(sourceId);
      if (finished.status === "succeeded") setMessage(organizationMessage(finished));
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (cause) {
      if (!signal.aborted) setMessage(cause instanceof Error ? cause.message : "Could not check processing. Refresh Home to see saved results.");
    } finally { if (!signal.aborted) setBusy(false); }
  }, [reload]);

  useEffect(() => {
    const tracking = new AbortController();
    controller.current = tracking;
    void (async () => {
      await reload();
      const response = await fetch("/api/jobs", { cache: "no-store", signal: tracking.signal });
      if (!response.ok) return;
      const jobs = await response.json() as Job[];
      const existing = jobs.find(job => job.kind === "source" && activeOrganization(job));
      if (existing?.subject_id && !tracking.signal.aborted) await observe(existing, existing.subject_id, tracking.signal);
    })().catch(() => { if (!tracking.signal.aborted) setMessage("Could not load sources. Refresh Home to try again."); });
    return () => { tracking.abort(); controller.current?.abort(); };
  }, [observe, reload]);
  useEffect(() => {
    const listener = (event: Event) => { void reload((event as CustomEvent<{ sourceId?: string }>).detail?.sourceId).catch(() => setMessage("Could not refresh sources.")); };
    window.addEventListener("focusos:sources-changed", listener);
    return () => window.removeEventListener("focusos:sources-changed", listener);
  }, [reload]);

  async function retry() {
    if (!selected || busy) return;
    setBusy(true); setMessage("Organizing...");
    controller.current?.abort();
    const tracking = new AbortController();
    controller.current = tracking;
    try {
      const job = await queueJob("source", selected.id);
      await observe(job, selected.id, tracking.signal);
    } catch (cause) { if (!tracking.signal.aborted) setMessage(cause instanceof Error ? cause.message : "Could not organize this source."); }
    finally { if (!tracking.signal.aborted) setBusy(false); }
  }

  async function remove() {
    if (!selected || selected.kind !== "gmail" || !window.confirm("Remove this imported source and its linked FocusOS data?")) return;
    setBusy(true);
    try {
      await json(await fetch("/api/sources/" + selected.id, { method: "DELETE" }));
      setSources((current) => current.filter((item) => item.id !== selected.id));
      selectedRef.current = null; setSelected(null); setExtraction(null); setMemories([]);
      setMessage("Imported source removed.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not remove source"); }
    finally { setBusy(false); }
  }

  return <section className="source-review">
    <div className="activity-columns">
      <div className="review-panel source-library">
        <div className="activity-panel-heading"><div><h2>Your sources</h2><p>{sources.length} saved {sources.length === 1 ? "source" : "sources"}</p></div></div>
        {sources.length === 0 ? <div className="activity-empty">No sources yet. Add a note or sync labeled Gmail to begin.</div> :
          <ul className="source-list">{sources.map((source) => <li key={source.id}>
            <button type="button" className={selected?.id === source.id ? "selected-source" : "secondary-button"}
              disabled={busy} onClick={() => void select(source).catch(() => setMessage("Could not load this source."))}>
              <span>{source.title}</span><small>{source.kind === "gmail" ? "Gmail" : source.kind === "task" ? "Manual task" : "Manual"} · {new Date(source.received_at).toLocaleDateString()}</small>
            </button>
          </li>)}</ul>}
      </div>
    </div>
    {selected && <div className="review-panel source-detail">
      <div className="activity-panel-heading"><div><h2>{selected.title}</h2><p>{selected.kind === "gmail" ? "Gmail source" : selected.kind === "task" ? "Manual task source" : "Manual source"} · {new Date(selected.received_at).toLocaleString()}</p></div></div>
      {extraction?.status === "ready" && <div className="activity-result-banner">Tasks and memories · {extraction.confirmed_item_keys.length} tasks · {memories.length} memories</div>}
      {extraction?.status === "processing" && <p role="status">Organizing this source. Results will appear here automatically.</p>}
      {extraction?.status === "failed" && <p role="alert">Could not organize this source. Your description is saved; try again later.</p>}
      {(!extraction || extraction.status === "failed" || (extraction.status === "ready" && (
        extraction.confirmed_item_keys.length < (extraction.validated_payload?.tasks.length ?? 0) ||
        memories.length < (extraction.validated_payload?.facts.length ?? 0) ||
        memories.some(memory => memory.embedding_status !== "ready")))) && selected.normalized_body && selected.kind !== "task" && <button type="button" onClick={() => void retry()} disabled={busy}>Retry organizing</button>}
      {extraction?.status === "ready" && extraction.validated_payload && <>
        <div className="activity-results-grid">
          <div><h3>Tasks</h3>{extraction.validated_payload.tasks.length === 0 ? <p>No tasks found.</p> :
            extraction.validated_payload.tasks.map((task) => <article className="activity-result" key={task.local_ref}><strong>{task.title}</strong><small>{extraction.confirmed_item_keys.includes(task.local_ref) ? "Saved to tasks" : "Save incomplete"}</small><blockquote>{task.evidence[0]?.quote}</blockquote></article>)}</div>
          <div><h3>Memories</h3>{memories.length === 0 ? <p>No memories found in this source.</p> :
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
