"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { buildPlanningRequest, describePlanningFailure } from "./planning-feedback";

type Block = { task_ref: string; title: string; start: string; end: string; reason: string };
type Plan = { status: string; summary: string; requested_minutes: number; scheduled_minutes: number;
  shortfall_minutes: number; blocks: Block[]; questions: string[]; assumptions: string[] };
type Run = { id: string; command: string; status: string; stage: string;
  checkpoint: { auto_calendar?: boolean; timezone?: string }; result: Plan | null; safe_error: string | null };
type CalendarAction = { title: string; start: string; end: string; timezone: string };
type ScheduledBlock = { id: string; block_index: number; status: string; payload: CalendarAction;
  authorization_mode: string; provider_link: string | null; safe_code: string | null };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const stages: Record<string, string> = {
  start: "Starting plan", tasks: "Reading tasks", calendar: "Checking Calendar",
  free_time: "Finding open time", memory: "Searching memories", planning: "Building plan",
};
const wait = (milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds));

async function readJson<T>(response: Response): Promise<T> {
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof value.error === "string" ? value.error : "Planning is temporarily unavailable.");
  return value as T;
}

function describeFailure(code: string | null): string {
  const reasons: Record<string, string> = {
    calendar_write_required: "Enable Calendar event writes in Google connections, then submit a new plan.",
    profile_required: "Save your timezone and working hours in Settings, then submit again.",
    calendar_reconnect_required: "Reconnect Google Calendar, then submit a new plan.",
    slot_conflict: "The time is no longer available. Submit a new plan.",
    plan_stale: "The time changed while scheduling. Submit a new plan.",
    task_changed: "A task changed or was completed. Submit a new plan.",
    calendar_rate_limited: "Google Calendar is rate limiting requests. This event has not been confirmed; reload this page later.",
    provider_outcome_unknown: "Google Calendar has not confirmed the outcome. Reload this page to reconcile it before creating another plan.",
  };
  return code ? reasons[code] ?? `Calendar could not confirm this event (${code}). Reload this page to retry safely.` : "Calendar could not confirm this event. Reload this page to retry safely.";
}

export function AgentConsole({ initialRunId }: { initialRunId?: string }) {
  const [command, setCommand] = useState("");
  const [duration, setDuration] = useState("");
  const [allowSplit, setAllowSplit] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<ScheduledBlock[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const requestKey = useRef<string | null>(null);
  const running = useRef(false);

  const loadEvents = useCallback(async (id: string) => {
    const response = await fetch(`/api/approvals?run_id=${id}`, { cache: "no-store" });
    if (response.ok) setEvents((await readJson<ScheduledBlock[]>(response)).filter(item => item.authorization_mode === "automatic"));
  }, []);

  const drive = useCallback(async (initial: Run) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setMessage(null);
    let current = initial;
    try {
      for (let attempt = 0; attempt < 40 && (current.status === "waiting" || current.status === "running"); attempt++) {
        if (current.status === "running") await wait(2200);
        current = await readJson<Run>(await fetch(`/api/agent/runs/${current.id}/continue`, { method: "POST" }));
        setRun(current);
      }
      if (current.status === "waiting" || current.status === "running") {
        throw new Error("Planning is taking longer than expected. Reload this run to continue automatically.");
      }
      if (current.status !== "succeeded" || current.result?.status !== "proposed") {
        setMessage(current.result?.questions?.join(" ") || (current.safe_error ? describePlanningFailure(current.safe_error) : null) || current.result?.summary || "No work block could be scheduled. Check your tasks and Calendar availability.");
        return;
      }
      if (!current.checkpoint.auto_calendar) return;
      if (current.result.blocks.length === 0) throw new Error("No work block could be scheduled. Check your tasks and Calendar availability.");
      for (let index = 0; index < current.result.blocks.length; index++) {
        let action: ScheduledBlock | null = null;
        for (let attempt = 0; attempt < 4; attempt++) {
          action = await readJson<ScheduledBlock>(await fetch(`/api/agent/runs/${current.id}/blocks/${index}/auto`, { method: "POST" }));
          setEvents(previous => [...previous.filter(item => item.block_index !== index), action!].sort((a, b) => a.block_index - b.block_index));
          if (action.status === "succeeded" || ["stale", "failed"].includes(action.status)) break;
          await wait(1800 * (attempt + 1));
        }
        if (action?.status !== "succeeded") {
          throw new Error(`Block ${index + 1}: ${describeFailure(action?.safe_code ?? null)}`);
        }
      }
      await loadEvents(current.id);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Planning is temporarily unavailable.");
      await loadEvents(current.id).catch(() => {});
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [loadEvents]);

  useEffect(() => {
    if (!initialRunId || !UUID.test(initialRunId)) return;
    let cancelled = false;
    fetch(`/api/agent/runs/${initialRunId}`, { cache: "no-store" }).then(response => readJson<Run>(response))
      .then(async saved => {
        if (cancelled) return;
        setRun(saved);
        await loadEvents(saved.id);
        if (!cancelled && saved.checkpoint.auto_calendar) void drive(saved);
      }).catch(() => { if (!cancelled) setMessage("Run unavailable. Please sign in and try again."); });
    return () => { cancelled = true; };
  }, [initialRunId, drive, loadEvents]);

  async function start(event: FormEvent) {
    event.preventDefault();
    if (running.current) return;
    setBusy(true);
    setMessage(null);
    setEvents([]);
    try {
      if (!requestKey.current) requestKey.current = crypto.randomUUID();
      const next = await readJson<Run>(await fetch("/api/agent/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPlanningRequest(command, duration, allowSplit, requestKey.current)),
      }));
      requestKey.current = null;
      setRun(next);
      window.history.replaceState(null, "", `/agent/${next.id}`);
      await drive(next);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Planning is temporarily unavailable.");
      setBusy(false);
    }
  }

  const confirmed = events.filter(item => item.status === "succeeded");
  const expected = run?.result?.blocks.length ?? 0;
  const completed = run?.result?.status === "proposed" && expected > 0 && confirmed.length === expected;
  const timezone = run?.checkpoint.timezone || "Asia/Jakarta";
  function formatTime(value: string) {
    try { return new Intl.DateTimeFormat("id-ID", { dateStyle: "full", timeStyle: "short", timeZone: timezone }).format(new Date(value)); }
    catch { return new Date(value).toLocaleString("id-ID"); }
  }
  return <section className="agent-console">
    {!run ? <form className="review-panel" onSubmit={start}>
      <label>What should FocusOS schedule?<textarea required maxLength={1000} rows={4} value={command} onChange={event => setCommand(event.target.value)} placeholder="Find an hour this week to work on my report" /></label>
      <label>Duration override (minutes, optional)<input type="number" min={15} max={480} value={duration} onChange={event => setDuration(event.target.value)} /></label>
      <label><input type="checkbox" checked={allowSplit} onChange={event => setAllowSplit(event.target.checked)} /> Allow multiple work blocks</label>
      <p>Leave duration empty to use the time in your request or the saved task estimate. An explicit duration must match your request.</p>
      <p>Submitting starts planning and creates valid work blocks in your Google Calendar automatically.</p>
      <button disabled={busy || !command.trim()} type="submit">{busy ? "Starting…" : "Plan and add to Calendar"}</button>
    </form> : null}
    {message ? <p role="alert" className="agent-alert">{message}</p> : null}
    {run ? <div className="review-panel" aria-live="polite">
      <h2>{completed ? "Added to Google Calendar" : busy ? "Scheduling your work" : "Planning result"}</h2>
      <p>{run.command}</p>
      {busy ? <p className="agent-progress">{run.status === "succeeded" ? "Adding work blocks to Google Calendar…" : stages[run.stage] || "Planning…"}</p> : null}
      {run.result ? <p>{run.result.summary}</p> : null}
      {run.safe_error && !message ? <p role="alert">{describePlanningFailure(run.safe_error)}</p> : null}
      {run.result?.assumptions?.map((assumption, index) => <p key={`assumption-${index}`}>{assumption}</p>)}
      {run.result?.status === "proposed" ? <div className="agent-block-list">
        {run.result.blocks.map((block, index) => {
          const action = events.find(item => item.block_index === index);
          return <article className="review-card" key={`${index}-${block.start}`}>
            <h3>{action?.payload.title || block.title}</h3>
            <p>{formatTime(action?.payload.start || block.start)} – {new Intl.DateTimeFormat("id-ID", { timeStyle: "short", timeZone: timezone }).format(new Date(action?.payload.end || block.end))} {timezone}</p>
            <p>{action?.status === "succeeded" ? "Added to Calendar" : busy ? "Checking and adding to Calendar…" : "Not confirmed in Calendar"}</p>
            {action?.status === "succeeded" ? <a href={action.provider_link || "https://calendar.google.com/calendar/u/0/r"} target="_blank" rel="noopener noreferrer">{action.provider_link ? "Open event in Google Calendar ↗" : "Open Google Calendar ↗"}</a> : null}
          </article>;
        })}
      </div> : null}
      {run.result?.status !== "proposed" && run.result?.questions.map((question, index) => <p key={index}>{question}</p>)}
      {!run.checkpoint.auto_calendar && run.result?.status === "proposed" ? <p>This older run was not submitted for automatic scheduling. Start a new plan to add events automatically.</p> : null}
      <p><a href={`/agent/${run.id}`}>Permanent run link</a> · <a href="/agent">Plan another activity</a></p>
    </div> : null}
  </section>;
}