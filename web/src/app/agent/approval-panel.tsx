"use client";

import { useCallback, useEffect, useState } from "react";

type Action = { title: string; start: string; end: string; timezone: string; calendar_id: string;
  source_id: string | null; connection_id: string; guests: string[]; send_updates: string };
type Approval = { id: string; run_id: string; block_index: number; status: string; expires_at: string;
  payload: Action; provider_event_id: string | null; provider_link: string | null; safe_code: string | null };
type PlanBlock = { title: string; evidence_refs: string[] };
type Audit = { action_status: string; expected_blocks: number; succeeded_count: number;
  transitions: { approval_id: string; block_index: number; status: string; safe_code: string | null; occurred_at: string }[] };

async function readJson(response: Response) {
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Approval unavailable");
  return value;
}

export function ApprovalPanel({ runId, blocks }: { runId: string; blocks: PlanBlock[] }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    const [approvalResult, auditResult] = await Promise.allSettled([
      readJson(await fetch(`/api/approvals?run_id=${runId}`, { cache: "no-store" })),
      readJson(await fetch(`/api/agent/runs/${runId}/audit`, { cache: "no-store" })),
    ]);
    if (approvalResult.status === "rejected") throw approvalResult.reason;
    setApprovals(approvalResult.value as Approval[]);
    if (auditResult.status === "fulfilled") {
      setAudit(auditResult.value as Audit);
      setError((current) => current?.startsWith("Action history is temporarily unavailable") ? null : current);
    } else {
      setAudit(null);
      setError("Action history is temporarily unavailable; approval controls are still available.");
    }
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
  async function execute(index: number, approvalId: string) {
    setError(null); setBusy(index);
    try {
      await readJson(await fetch(`/api/approvals/${approvalId}/execute`, { method: "POST" }));
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Calendar action unavailable"); await refresh().catch(() => {}); }
    finally { setBusy(null); }
  }
  return <section className="review-panel" aria-label="Calendar approvals"><h2>Calendar actions</h2>
    <p>Each work block needs its own review and execution. A saved approval does not itself create an event.</p>
    {audit ? <p>Calendar workflow: <strong>{audit.action_status}</strong>. Confirmed events: {audit.succeeded_count} of {audit.expected_blocks}.</p> : null}
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
          {approval.safe_code ? <p role="status">Status detail: {approval.safe_code}</p> : null}
          {approval.status === "succeeded" ? <p>Google confirmed event: {approval.provider_link ? <a href={approval.provider_link} target="_blank" rel="noopener noreferrer">Open in Google Calendar</a> : approval.provider_event_id}</p> : null}
          {["approved", "executing", "unknown"].includes(approval.status) ? <button disabled={busy !== null} onClick={() => execute(index, approval.id)}>{approval.status === "approved" ? "Create approved event" : "Check or reconcile outcome"}</button> : null}
          {approval.status === "pending" ? <div className="task-actions"><button disabled={busy !== null} onClick={() => decide(index, approval.id, "approve")}>Approve exact event</button>
            <button className="secondary-button" disabled={busy !== null} onClick={() => decide(index, approval.id, "reject")}>Reject</button></div> : null}
        </>}</article>;
    })}
    {audit?.transitions.length ? <div><h3>Action history</h3><ol>{audit.transitions.map((item, index) => <li key={`${item.approval_id}-${index}`}>Block {item.block_index + 1}: {item.status} at {new Date(item.occurred_at).toLocaleString()}{item.safe_code ? ` (${item.safe_code})` : ""}</li>)}</ol></div> : null}
    <button className="secondary-button" disabled={busy !== null} onClick={() => refresh().catch(() => setError("Approval list unavailable"))}>Reload approvals</button>
  </section>;
}
