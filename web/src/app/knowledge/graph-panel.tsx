"use client";
import { useCallback, useEffect, useState } from "react";

export type GraphStats = { entities: number; relations: number; indexed_memories: number };

export function graphSummary(stats: GraphStats): string {
  if (!stats.indexed_memories) return "No memories are connected yet. New notes are added automatically; index older ones below.";
  return `${stats.entities} people, projects and places, linked by ${stats.relations} relations from ${stats.indexed_memories} memories. Questions can follow these links, for example from a project's code name to its audience.`;
}

export function GraphPanel() {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const load = useCallback(() => {
    fetch("/api/product/graph", { cache: "no-store" })
      .then(response => response.ok ? response.json() : null)
      .then(result => { if (result && typeof result.entities === "number") setStats(result as GraphStats); })
      .catch(() => { /* Optional summary. */ });
  }, []);
  useEffect(() => { load(); }, [load]);
  async function backfill() {
    setBusy(true); setNotice("");
    try {
      const response = await fetch("/api/product/graph/backfill", { method: "POST" });
      if (!response.ok) throw new Error();
      const result = await response.json() as { indexed: number; remaining: number };
      setNotice(result.indexed ? `Connected ${result.indexed} memories.${result.remaining ? ` ${result.remaining} left; run again to continue.` : ""}`
        : result.remaining ? "The AI service is busy. Try again in a minute." : "Every memory is already connected.");
      load();
    } catch { setNotice("Could not index memories right now."); }
    finally { setBusy(false); }
  }
  return <div className="graph-panel-body">
    <p className="check-in-insight">{stats ? graphSummary(stats) : "Loading your knowledge graph…"}</p>
    <div className="graph-actions"><button type="button" onClick={() => void backfill()} disabled={busy}>{busy ? "Indexing..." : "Index older memories"}</button>
      {notice && <span role="status">{notice}</span>}</div>
  </div>;
}
