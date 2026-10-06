"use client";
import { useCallback, useEffect, useState } from "react";
type Memory = { id: string; source_id: string; text: string; evidence_quote: string; embedding_status: string; embedding_error: string | null };
export function MemoryLibrary() {
  const [memories, setMemories] = useState<Memory[]>([]), [error, setError] = useState(""), [busy, setBusy] = useState(false), [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Memory | null>(null);
  const load = useCallback(async () => { setBusy(true); try { const r = await fetch("/api/memories", { cache: "no-store" }); const data = await r.json(); if (!r.ok) throw new Error(); setMemories(data.memories); } catch { setError("Memory library could not be loaded."); } finally { setBusy(false); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function act(id: string, action: "supersede" | "embed") {
    setBusy(true); setError("");
    try {
      const r = await fetch(`/api/memories/${id}/${action}`, { method: "POST" }); const data = await r.json();
      if (!r.ok || action === "supersede" && data.superseded !== true) throw new Error();
      if (action === "embed" && data.state === "failed") setError("Embedding is unavailable. This fact remains saved; try again later.");
      setSelected(null); await load();
    } catch { setError("Memory update could not be confirmed. Reload before retrying."); }
    finally { setBusy(false); }
  }
  const filtered = memories.filter(m => `${m.text} ${m.evidence_quote}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="workspace"><header className="section-heading"><h2>Saved memory library</h2><p>Latest 50 active facts. Search above retrieves relevant memories across the full library.</p></header>
    <label>Filter this list<input value={query} onChange={e => setQuery(e.target.value)} /></label>{error && <p role="alert">{error}</p>}
    {!busy && filtered.length === 0 && <p>No matching active memory.</p>}
    <div className="workspace-list">{filtered.map(m => <article className="review-card" key={m.id}><h3>{m.text}</h3><blockquote>{m.evidence_quote}</blockquote><p>Search index: {m.embedding_status}</p><a href={`/activity?source=${m.source_id}`}>View source</a><div className="workspace-actions">{m.embedding_status !== "ready" && <button disabled={busy} onClick={() => void act(m.id, "embed")}>Retry indexing</button>}<button disabled={busy} onClick={() => setSelected(m)}>Remove from search</button></div></article>)}</div>
    {selected && <div className="review-panel" role="region" aria-label="Remove memory"><h3>Remove this fact from future searches?</h3><p>{selected.text}</p><p>Its source and tasks will remain saved.</p><div className="workspace-actions"><button disabled={busy} onClick={() => void act(selected.id, "supersede")}>Remove fact</button><button onClick={() => setSelected(null)}>Keep fact</button></div></div>}
  </section>;
}
