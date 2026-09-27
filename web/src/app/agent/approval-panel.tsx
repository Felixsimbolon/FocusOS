"use client";

import { useCallback, useEffect, useState } from "react";

type Action = { title: string; start: string; end: string; timezone: string; calendar_id: string;
  source_id: string | null; connection_id: string; guests: string[]; send_updates: string };
type Approval = { id: string; run_id: string; block_index: number; status: string; expires_at: string;
  payload: Action; provider_event_id: string | null; provider_link: string | null; safe_code: string | null };
type PlanBlock = { title: string; evidence_refs: string[] };

async function readJson(response: Response) {
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Approval unavailable");
  return value;
}

export function ApprovalPanel({ runId, blocks }: { runId: string; blocks: PlanBlock[] }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    setApprovals(await readJson(await fetch(`/api/approvals?run_id=${runId}`, { cache: "no-store" })));
  }, [runId]);
  useEffect(() => { refresh().catch(() => setError("Approval list unavailable")); }, [refresh]);
  async function propose(index: number) {
    setError(null); setBusy(index);
    try {
      await readJson(await fetch(`/api/agent/runs/${runId}/propose-event`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ block_index: index }),
      }));
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Proposal unavailable"); }
    finally { setBusy(null); }
  }
  async function decide(index: number, approvalId: string, decision: "approve" | "reject") {
    setError(null); setBusy(index);
    try {
      await readJson(await fetch(`/api/approvals/${approvalId}/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }),
      }));
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Decision unavailable"); await refresh().catch(() => {}); }
    finally { setBusy(null); }
  }
  return <section className="review-panel" aria-label="Calendar approvals"><h2>Calendar actions</h2>
    <p>Each work block needs its own review. Approval is saved; event creation is a separate next step.</p>
    {error ? <p role="alert">{error}</p> : null}
    {blocks.map((block, index) => {
      const approval = approvals.find(item => item.block_index === index);
      return <article key={index} className="review-card"><h3>{block.title}</h3>
        {!approval ? <button disabled={busy !== null} onClick={() => propose(index)}>Prepare approval for block {index + 1}</button> : <>
          <p>Status: <strong>{approval.status}</strong>. Expires: {new Date(approval.expires_at).toLocaleString()}.</p>
          <p>Event: {approval.payload.title}. {new Date(approval.payload.start).toLocaleString()} – {new Date(approval.payload.end).toLocaleString()} ({approval.payload.timezone}).</p>
          <p>Calendar: {approval.payload.calendar_id}. Google connection: {approval.payload.connection_id}. <a href="/settings/connections">Inspect connected account</a>.</p>
          <p>Linked source: {approval.payload.source_id ?? "none"}. {approval.payload.source_id ? <a href="/activity">Review source</a> : null}</p>
          {block.evidence_refs.length ? <p>Evidence references: {block.evidence_refs.join(", ")}</p> : null}
          <p>Guests: none. Notifications: none.</p>
          {approval.status === "pending" ? <div className="task-actions"><button disabled={busy !== null} onClick={() => decide(index, approval.id, "approve")}>Approve exact event</button>
            <button className="secondary-button" disabled={busy !== null} onClick={() => decide(index, approval.id, "reject")}>Reject</button></div> : null}
        </>}</article>;
    })}
    <button className="secondary-button" disabled={busy !== null} onClick={() => refresh().catch(() => setError("Approval list unavailable"))}>Reload approvals</button>
  </section>;
}
