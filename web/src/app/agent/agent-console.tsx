"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApprovalPanel } from "./approval-panel";

type Block = { task_ref: string; title: string; start: string; end: string; reason: string; evidence_refs: string[] };
type Plan = { status: string; summary: string; requested_minutes: number; scheduled_minutes: number;
  shortfall_minutes: number; blocks: Block[]; assumptions: string[]; questions: string[]; actionable: boolean };
type Run = { id: string; command: string; status: string; stage: string; model_turns: number; tool_calls_count: number;
  checkpoint: { tasks?: unknown[]; tasks_truncated?: boolean; calendar?: { event_count: number; fetched_at: string };
    free_time?: { slots: unknown[]; shortfall_minutes: number }; memory_search?: { mode: string; matches: unknown[] } };
  result: Plan | null; safe_error: string | null };
type Tool = { ordinal: number; name: string; status: string; safe_code: string | null };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function readJson(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Agent run unavailable");
  return data;
}

export function AgentConsole({ initialRunId }: { initialRunId?: string }) {
  const [command, setCommand] = useState("");
  const [duration, setDuration] = useState(60);
  const [allowSplit, setAllowSplit] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestKey = useRef<string | null>(null);
  const currentId = run?.id || initialRunId;
  const refresh = useCallback(async (id: string) => {
    const next: Run = await readJson(await fetch(`/api/agent/runs/${id}`, { cache: "no-store" }));
    setRun(next);
    const trace = await fetch(`/api/agent/runs/${id}/tools`, { cache: "no-store" });
    if (trace.ok) setTools(await trace.json());
  }, []);
  useEffect(() => { if (initialRunId && UUID.test(initialRunId)) refresh(initialRunId).catch(() => setError("Run unavailable")); }, [initialRunId, refresh]);
  async function start(event: FormEvent) {
    event.preventDefault();
    setError(null); setBusy(true);
    try {
      if (!requestKey.current) requestKey.current = crypto.randomUUID();
      const next: Run = await readJson(await fetch("/api/agent/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_key: requestKey.current, command, duration_minutes: duration, allow_split: allowSplit }),
      }));
      setRun(next); setTools([]); requestKey.current = null;
      window.history.replaceState(null, "", `/agent/${next.id}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent run unavailable"); }
    finally { setBusy(false); }
  }
  async function advance() {
    if (!currentId || !UUID.test(currentId)) return;
    setError(null); setBusy(true);
    try {
      await readJson(await fetch(`/api/agent/runs/${currentId}/continue`, { method: "POST" }));
      await refresh(currentId);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent run unavailable"); await refresh(currentId).catch(() => {}); }
    finally { setBusy(false); }
  }
  return <section className="agent-console">
    {!initialRunId && !run ? <form className="review-panel" onSubmit={start}>
      <label>What should FocusOS plan?<textarea required maxLength={1000} rows={4} value={command} onChange={event => setCommand(event.target.value)} placeholder="Find an hour this week to work on my report" /></label>
      <label>Minutes needed<input type="number" min={15} max={480} value={duration} onChange={event => setDuration(Number(event.target.value))} /></label>
      <label><input type="checkbox" checked={allowSplit} onChange={event => setAllowSplit(event.target.checked)} /> Allow multiple work blocks</label>
      <button disabled={busy || !command.trim()} type="submit">{busy ? "Starting…" : "Start planning"}</button>
    </form> : null}
    {error ? <p role="alert">{error}</p> : null}
    {run ? <div className="review-panel"><h2>Run status: {run.status}</h2><p>{run.command}</p>
      <p>Stage: {run.stage}. Model turns: {run.model_turns}. Read tools completed: {run.tool_calls_count}.</p>
      {run.safe_error ? <p role="alert">Stopped safely: {run.safe_error}</p> : null}
      {run.status === "waiting" || run.status === "running" ? <button disabled={busy} onClick={advance}>{busy ? "Working…" : run.status === "running" ? "Check planning stage" : "Continue run"}</button> : null}
      <button className="secondary-button" disabled={busy} onClick={() => refresh(run.id).catch(() => setError("Run unavailable"))}>Reload status</button>
      <p><a href={`/agent/${run.id}`}>Permanent run link</a></p></div> : null}
    {run ? <div className="review-panel"><h2>Retrieved context</h2>
      <p>Tasks: {run.checkpoint.tasks?.length ?? 0}{run.checkpoint.tasks_truncated ? " (more exist)" : ""}. Calendar busy events: {run.checkpoint.calendar?.event_count ?? "not fetched"}.</p>
      <p>Candidate slots: {run.checkpoint.free_time?.slots.length ?? 0}. Memory matches: {run.checkpoint.memory_search?.matches.length ?? 0} ({run.checkpoint.memory_search?.mode ?? "not searched"}).</p>
      {run.checkpoint.calendar ? <p>Calendar snapshot: {new Date(run.checkpoint.calendar.fetched_at).toLocaleString()}.</p> : null}
    </div> : null}
    {run?.result ? <div className="review-panel"><h2>{run.result.status === "proposed" ? "Proposed plan" : run.result.status === "insufficient_time" ? "Not enough time" : "Clarification needed"}</h2>
      <p>{run.result.summary}</p><p>Requested: {run.result.requested_minutes} min. Scheduled: {run.result.scheduled_minutes} min. Unscheduled: {run.result.shortfall_minutes} min.</p>
      {run.result.blocks.map(block => <article className="review-card" key={block.start + block.task_ref}><h3>{block.title}</h3><p>{new Date(block.start).toLocaleString()} – {new Date(block.end).toLocaleString()}</p><p>{block.reason}</p>{block.evidence_refs.length ? <p>Evidence: {block.evidence_refs.join(", ")}</p> : null}</article>)}
      {run.result.questions.map((question, index) => <p key={index}>Question: {question}</p>)}
      {run.result.assumptions.map((assumption, index) => <p key={index}>Assumption: {assumption}</p>)}
      <p>Proposal only. No calendar event has been created.</p></div> : null}
    {run?.result?.status === "proposed" ? <ApprovalPanel runId={run.id} blocks={run.result.blocks} /> : null}
    {run ? <div className="review-panel"><h2>Read tool history</h2>{tools.length ? <ol>{tools.map(tool => <li key={tool.ordinal}>{tool.name}: {tool.status}{tool.safe_code ? ` (${tool.safe_code})` : ""}</li>)}</ol> : <p>No completed read tool recorded yet.</p>}</div> : null}
  </section>;
}
