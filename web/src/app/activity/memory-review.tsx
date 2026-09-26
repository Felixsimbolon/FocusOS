"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Memory = { id: string; source_id: string; project_id: string | null; text: string; evidence_quote: string; status: string; embedding_status?: string; embedding_error?: string | null };
type Project = { id: string; name: string };

export function MemoryReview({ sourceId, body, projects }: {
  sourceId: string; body: string; projects: Project[];
}) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [text, setText] = useState("");
  const [quote, setQuote] = useState("");
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useRef<{ key: string; payload: string } | null>(null);

  async function refresh() {
    const response = await fetch("/api/memories", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load memories");
    const data = await response.json();
    setMemories(data.memories);
  }
  useEffect(() => { void refresh().catch(() => setMessage("Could not load memories")); }, [sourceId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!body.includes(quote.trim())) { setMessage("Evidence must be an exact quote from this source."); return; }
    setBusy(true); setMessage("");
    const fields = { source_id: sourceId, project_id: projectId || null,
      text: text.trim(), evidence_quote: quote.trim() };
    const payload = JSON.stringify(fields);
    if (!pending.current || pending.current.payload !== payload)
      pending.current = { key: crypto.randomUUID(), payload };
    try {
      const response = await fetch("/api/memories", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_key: pending.current.key, ...fields }),
      });
      if (!response.ok) throw new Error("Could not confirm memory");
      pending.current = null;
      await refresh();
      setText(""); setQuote("");
      setMessage("Memory confirmed. Embedding can be requested separately.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Memory unavailable"); }
    finally { setBusy(false); }
  }

  async function embed(id: string) {
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/memories/" + id + "/embed", { method: "POST" });
      if (!response.ok) throw new Error("Could not embed memory");
      const result = await response.json();
      await refresh();
      setMessage(result.state === "ready" || result.state === "reused"
        ? "Memory embedding ready." : result.state === "busy"
          ? "Embedding is already running." : "Embedding could not finish; the confirmed fact is still saved.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Embedding unavailable"); }
    finally { setBusy(false); }
  }

  async function supersede(id: string) {
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/memories/" + id + "/supersede", { method: "POST" });
      if (!response.ok) throw new Error("Could not supersede memory");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Memory unavailable"); }
    finally { setBusy(false); }
  }

  const sourceMemories = memories.filter((item) => item.source_id === sourceId);
  return <div className="memory-review">
    <h3>Confirmed memories from this source</h3>
    <p>Save only a fact you checked. Copy an exact quote from the source as evidence.</p>
    <form className="task-form" onSubmit={(event) => void save(event)}>
      <label>Confirmed fact<input value={text} onChange={(event) => setText(event.target.value)} maxLength={500} required /></label>
      <label>Exact source quote<textarea value={quote} onChange={(event) => setQuote(event.target.value)} maxLength={500} rows={2} required /></label>
      <label>Project<select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
        <option value="">No project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select></label>
      <button type="submit" disabled={busy || !text.trim() || !quote.trim()}>Confirm memory</button>
    </form>
    {sourceMemories.length ? <ul>{sourceMemories.map((item) =>
      <li key={item.id}><strong>{item.text}</strong><blockquote>{item.evidence_quote}</blockquote>
        <p>Embedding: {item.embedding_status ?? "pending"}{item.embedding_error ? " (" + item.embedding_error + ")" : ""}</p>
        <button type="button" className="secondary-button" disabled={busy || item.embedding_status === "ready"}
          onClick={() => void embed(item.id)}>Embed / retry</button>{" "}
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void supersede(item.id)}>
          Mark outdated
        </button></li>)}</ul> : <p>No active memory from this source.</p>}
    {message && <p role="status">{message}</p>}
  </div>;
}
