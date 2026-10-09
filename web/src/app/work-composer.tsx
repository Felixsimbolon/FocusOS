"use client";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { PaginatedItems } from "./paginated-items";
import { type Job } from "./jobs/client";
import { activeOrganization, followOrganization } from "./organization";

type CalendarBlock = { title: string; start: string; end: string; timezone: string; link: string | null };
export function workMessage(job: Job): string {
  const result = job.result || {};
  const saved = Number(result.tasks_saved || 0);
  const memories = Number(result.memories_saved || 0);
  if (job.status === "succeeded") return Number(result.blocks_scheduled) > 0
    ? `${Number(result.blocks_scheduled)} Calendar block(s) created.${saved ? ` ${saved} task(s) also saved.` : ""}`
    : saved || memories ? `Saved ${saved} task(s) and ${memories} memory item(s).` : "No tasks or facts found in this description.";
  if (["failed", "expired", "cancelled"].includes(job.status)) {
    const message = typeof result.message === "string" ? result.message : job.status === "expired"
      ? "This processing request expired. Your saved results are kept. Check Calendar before submitting a new request."
      : ["intent_unavailable", "provider_unconfigured", "extraction_unavailable", "embedding_unavailable"].includes(job.safe_error || "")
        ? "The AI service is unavailable. Your saved results are kept; try again when the service is available."
        : job.safe_error === "intent_invalid"
        ? "Could not understand the request. Try a clearer description with a day, time window, and duration."
        : job.safe_error === "capture_incomplete"
        ? "Some tasks or memories could not be organized. Your saved results are kept. Check the source before resubmitting."
        : job.safe_error === "database_unavailable"
        ? "Storage is temporarily unavailable. Your saved results are kept. Check existing tasks before resubmitting."
        : ["google_reconnect_required", "calendar_reconnect_required"].includes(job.safe_error || "")
        ? "Reconnect Google Calendar before scheduling. Your saved results are kept."
        : result.intent === "capture"
        ? "Could not finish organizing this description. Any saved tasks are kept. Check existing tasks before resubmitting."
        : "Could not finish this request. Any saved results are kept. Check existing tasks and Calendar before resubmitting.";
    return `${message}${saved || memories ? ` Already saved: ${saved} task(s), ${memories} memories.` : ""}${Number(result.blocks_scheduled) > 0 ? ` Already scheduled: ${Number(result.blocks_scheduled)} block(s). Check Calendar before retrying.` : ""}`;
  }
  if (job.safe_error) return `Service temporarily unavailable. Retrying after ${new Date(job.available_at).toLocaleTimeString()}...`;
  return result.intent === "schedule" || result.intent === "both" ? "Finding a free slot and adding it to Calendar..." : "Understanding and organizing your request...";
}
export function WorkComposer() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [blocks, setBlocks] = useState<CalendarBlock[]>([]);
  const [defaultDuration, setDefaultDuration] = useState(false);
  const [warning, setWarning] = useState("");
  const controller = useRef<AbortController | null>(null);
  const pending = useRef<{ text: string; key: string } | null>(null);
  const observe = useCallback(async (job: Job, signal: AbortSignal) => {
    setBusy(true);
    try {
      const finished = await followOrganization(job, current => {
        setMessage(activeOrganization(current) ? workMessage(current) : "");
        setBlocks((current.result?.blocks || []) as CalendarBlock[]);
      }, signal);
      setDefaultDuration(finished.result?.default_duration === true);
      setWarning(typeof finished.result?.warning === "string" ? finished.result.warning : "");
      if (finished.status === "succeeded") { setMessage(workMessage(finished)); setText(""); }
      else setError(workMessage(finished));
      pending.current = null;
      window.dispatchEvent(new Event("focusos:tasks-changed"));
      window.dispatchEvent(new Event("focusos:schedule-changed"));
      window.dispatchEvent(new CustomEvent("focusos:sources-changed", { detail: { sourceId: finished.result?.source_id } }));
    } catch (cause) {
      if (!signal.aborted) setError(cause instanceof Error ? cause.message : "Could not check progress. Refresh to resume.");
    } finally { if (!signal.aborted) setBusy(false); }
  }, []);
  useEffect(() => {
    const tracking = new AbortController(); controller.current = tracking;
    void (async () => {
      const response = await fetch("/api/jobs", { cache: "no-store", signal: tracking.signal });
      if (!response.ok) return;
      const jobs = await response.json() as Job[];
      for (const job of jobs.filter(item => item.kind === "planning" && activeOrganization(item))) {
        const detail = await fetch(`/api/agent/runs/${job.subject_id}`, { cache: "no-store", signal: tracking.signal });
        if (detail.ok && (await detail.json()).checkpoint?.entrypoint === "unified") {
          await observe(job, tracking.signal); break;
        }
      }
    })().catch(() => { /* Submitting still works if recovery lookup is unavailable. */ });
    return () => { tracking.abort(); controller.current?.abort(); };
  }, [observe]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || !text.trim()) return;
    const description = text.trim();
    if (!pending.current || pending.current.text !== description) pending.current = { text: description, key: crypto.randomUUID() };
    setBusy(true); setError(""); setWarning(""); setBlocks([]); setDefaultDuration(false); setMessage("Understanding your request...");
    controller.current?.abort(); const tracking = new AbortController(); controller.current = tracking;
    try {
      const response = await fetch("/api/commands", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: description, request_key: pending.current.key }), signal: tracking.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not submit this request.");
      await observe(data.background_job, tracking.signal);
    } catch (cause) { if (!tracking.signal.aborted) { setMessage(""); setError(cause instanceof Error ? cause.message : "Could not submit. Retry the same text."); setBusy(false); } }
  }
  return <section id="composer" className={`work-composer${busy ? " is-processing" : ""}`} aria-labelledby="composer-heading" aria-busy={busy}>
    <div className="composer-layout">
      <div className="composer-intro"><span className="section-eyebrow">NEW REQUEST</span><h2 id="composer-heading">What do you need<br className="composer-heading-break" /> to get done?</h2><p>Write it as you would say it. Add one task or a whole list, find a time, or ask for both.</p>
        <a className="composer-context-link" href="/#schedule">See your scheduled work <span aria-hidden="true">&rarr;</span></a>
      </div>
      <form className="composer-form" onSubmit={event => void submit(event)}>
        <div className="composer-input-frame">
          <label className="sr-only" htmlFor="work-request">Work or schedule request</label>
          <textarea id="work-request" value={text} onChange={event => setText(event.target.value)} rows={5} maxLength={1000} required disabled={busy} aria-describedby="composer-help"
            placeholder={"Buat task berikut:\n1. Siapkan outline presentasi, deadline 13 Oktober, estimasi 30 menit.\n2. Buat halaman web, deadline 18 Oktober, estimasi 2 jam.\n\nAtau: cari waktu besok jam 13-16 untuk belajar selama 30 menit."} />
          <div className="composer-input-bottom"><span>Indonesian or English. Up to 10 tasks per list.</span><span aria-label={`${text.length} of 1000 characters`}>{text.length.toLocaleString()} / 1,000</span></div>
        </div>
        <div className="composer-footer"><small id="composer-help">Calendar requests create events automatically. Add a duration, or we use your task estimate or 30 minutes.</small>
          <button type="submit" disabled={busy || !text.trim()}>{busy ? <><span className="composer-progress" aria-hidden="true" />Working...</> : <>Send request <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M5 12h14M13 6l6 6-6 6" /></svg></>}</button>
        </div>
      </form>
    </div>
    {(message || error || warning || blocks.length > 0) && <div className="composer-response">
      {message && <p role="status" aria-live="polite" className="composer-message">{message}</p>}
      {error && <p role="alert" className="composer-message">{error}</p>}
      {warning && <p role="alert" className="composer-message composer-warning">{warning}</p>}
      {defaultDuration && blocks.length > 0 && <p className="composer-note">Duration used: 30 minutes.</p>}
      {blocks.length > 0 && <PaginatedItems as="ul" className="composer-results" label="created Calendar blocks" pageSize={3} items={blocks.map((block, index) => <li key={`${block.start}-${index}`}><strong>{block.title}</strong>
        <span>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: block.timezone }).format(new Date(block.start))} - {new Intl.DateTimeFormat(undefined, { timeStyle: "short", timeZone: block.timezone }).format(new Date(block.end))} ({block.timezone})</span>
        {block.link && <a href={block.link} target="_blank" rel="noopener noreferrer">Open in Google Calendar</a>}</li>)} />}
    </div>}
  </section>;
}
