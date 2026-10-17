"use client";
import { useCallback, useEffect, useState } from "react";

export type PendingBlock = { id: string; title: string; start: string; end: string; timezone: string; planned_minutes: number };
type Factor = { factor: number; low: number; high: number; sessions: number; scope: string; applied: boolean };
export type Estimates = { overall: Factor; projects: Record<string, Factor>; min_sessions: number };
export type Outcome = "done" | "partial" | "skipped";

/** Minutes the work really needs: time spent when done, spent plus still needed when partial. */
export function checkInMinutes(outcome: Outcome, planned: number, minutes: number): number | null {
  if (outcome === "skipped") return null;
  const value = outcome === "partial" ? planned + minutes : minutes;
  return Math.min(1440, Math.max(1, Math.round(value)));
}

export function estimateMessage(estimates: Estimates): string {
  const { overall, min_sessions: needed } = estimates;
  if (overall.sessions < needed)
    return `Check in after ${needed} blocks to start adaptive estimates (${overall.sessions} of ${needed} so far).`;
  const factor = overall.factor.toFixed(1);
  if (!overall.applied) return `Your work usually takes about as long as planned (${overall.sessions} check-ins). Saved estimates are used as they are.`;
  return `Your work usually takes about ${factor}× the planned time (typically ${overall.low.toFixed(1)}–${overall.high.toFixed(1)}×, ${overall.sessions} check-ins). When you schedule a saved task without a duration, FocusOS books the corrected time.`;
}

function CheckInRow({ block, onSaved }: { block: PendingBlock; onSaved: () => void }) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [minutes, setMinutes] = useState(block.planned_minutes);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const when = `${new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: block.timezone }).format(new Date(block.start))}–${new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: block.timezone }).format(new Date(block.end))}`;
  async function save(chosen: Outcome) {
    setSaving(true); setError("");
    try {
      const response = await fetch(`/api/product/focus-blocks/${block.id}/check-in`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome: chosen, actual_minutes: checkInMinutes(chosen, block.planned_minutes, minutes) }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || "Could not save this check-in.");
      onSaved();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save this check-in."); }
    finally { setSaving(false); }
  }
  return <li className={`check-in${outcome ? " is-answering" : ""}`}>
    <p className="check-in-question">How did <strong>{block.title}</strong> go?</p>
    <p className="check-in-when">{when}, planned {block.planned_minutes} min</p>
    {outcome === null ? <div className="choices" role="group" aria-label={`How did ${block.title} go?`}>
      <button type="button" onClick={() => { setOutcome("done"); setMinutes(block.planned_minutes); }} disabled={saving}>Finished</button>
      <button type="button" onClick={() => { setOutcome("partial"); setMinutes(30); }} disabled={saving}>Not finished</button>
      <button type="button" className="quiet" onClick={() => void save("skipped")} disabled={saving}>Skipped</button>
    </div> : <form className="check-in-form" onSubmit={event => { event.preventDefault(); void save(outcome); }}>
      <label>{outcome === "done" ? "Minutes it took" : "Minutes still needed"}
        <input type="number" min={1} max={1440} value={minutes} onChange={event => setMinutes(Number(event.target.value))} required /></label>
      <button type="submit" disabled={saving || !(minutes >= 1)}>{saving ? "Saving..." : "Save"}</button>
      <button type="button" className="quiet" onClick={() => setOutcome(null)} disabled={saving}>Back</button>
    </form>}
    {error && <p role="alert" className="notice notice-error">{error}</p>}
  </li>;
}

export function CheckInList({ blocks, estimates, onSaved }: { blocks: PendingBlock[]; estimates: Estimates | null; onSaved: () => void }) {
  return <div className="check-ins">
    {estimates && <p className="insight">{estimateMessage(estimates)}</p>}
    {blocks.length ? <ul className="check-in-list" aria-label="Focus blocks to check in">{blocks.map(block => <CheckInRow key={block.id} block={block} onSaved={onSaved} />)}</ul>
      : <p className="quiet-line">No finished focus blocks to check in. After a block ends, tell FocusOS how long the work really took.</p>}
  </div>;
}

export function CheckInPanel() {
  const [blocks, setBlocks] = useState<PendingBlock[]>([]);
  const [estimates, setEstimates] = useState<Estimates | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    fetch("/api/product/check-ins", { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error()))
      .then(result => { setBlocks(Array.isArray(result) ? result : []); setError(""); })
      .catch(() => setError("Check-ins are unavailable right now."));
    fetch("/api/product/estimates", { cache: "no-store" })
      .then(response => response.ok ? response.json() : null)
      .then(result => { if (result && result.overall) setEstimates(result as Estimates); })
      .catch(() => { /* The insight is optional. */ });
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("focusos:schedule-changed", load);
    return () => window.removeEventListener("focusos:schedule-changed", load);
  }, [load]);
  return <>{error ? <p role="alert" className="notice notice-error">{error}</p> : <CheckInList blocks={blocks} estimates={estimates} onSaved={load} />}</>;
}
