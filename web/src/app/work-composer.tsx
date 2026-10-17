"use client";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { PaginatedItems } from "./paginated-items";
import { type Job } from "./jobs/client";
import { activeOrganization, followOrganization } from "./organization";

type CalendarBlock = { title: string; start: string; end: string; timezone: string; link: string | null };
type Reference = { kind: "task" | "memory" | "event"; title: string; detail?: string };
export type Answer = { question: string; status: "answered" | "no_reference" | "unavailable"; answer: string | null; references: Reference[] };
type ScheduleOutcome = { title: string; status: "scheduled" | "failed" | "clarify"; message?: string };
type EstimateAdjustment = { title: string; estimate_minutes: number; booked_minutes: number; factor: number; sessions: number };
/** Why a block is longer or shorter than the saved estimate. */
export function adjustmentNotes(result: Record<string, unknown>): string[] {
  const items = Array.isArray(result.estimate_adjustments) ? result.estimate_adjustments as EstimateAdjustment[] : [];
  return items.map(item => `Booked ${item.booked_minutes} min for ${item.title} instead of the ${item.estimate_minutes}-min estimate: your check-ins usually run about ${item.factor.toFixed(1)}× the plan (${item.sessions} check-ins). Write a duration to override this.`);
}
export const NO_REFERENCE_NOTE = "No reference found in your saved tasks, memories, or scheduled work.";
const REFERENCE_LABEL = { task: "Task", memory: "Memory", event: "Calendar" } as const;

/** Problems with single parts of a request that otherwise completed. */
export function partIssues(result: Record<string, unknown>): string[] {
  const schedules = Array.isArray(result.schedules) ? result.schedules as ScheduleOutcome[] : [];
  const notes = Array.isArray(result.notes) ? result.notes.filter((note): note is string => typeof note === "string") : [];
  return [...notes, ...schedules.filter(item => item.status !== "scheduled" && item.message)
    .map(item => schedules.length > 1 || item.status === "clarify" ? `${item.title}: ${item.message}` : item.message as string)];
}
/** Questions a finished request asked the user; a reply continues that request. */
export function openQuestions(job: Job): string[] {
  const result = job.result || {};
  const questions: string[] = [];
  if (job.status === "failed" && job.safe_error === "request_ambiguous" && typeof result.message === "string") questions.push(result.message);
  const schedules = Array.isArray(result.schedules) ? result.schedules as ScheduleOutcome[] : [];
  for (const item of schedules) if (item.status === "clarify" && item.message) questions.push(`${item.title || "Schedule"}: ${item.message}`);
  return questions.slice(0, 3);
}
export type Thread = { runId: string; request: string; questions: string[] };
export function ReplyThread({ thread, onDismiss }: { thread: Thread; onDismiss: () => void }) {
  return <div className="thread" role="group" aria-label="Reply to FocusOS">
    {thread.request && <p className="thread-turn thread-user"><span className="thread-speaker">You</span>{thread.request}</p>}
    {thread.questions.map((question, index) => <p key={index} className="thread-turn thread-agent"><span className="thread-speaker">FocusOS asks</span>{question}</p>)}
    <p className="thread-hint">Reply below in a few words, for example &ldquo;yang web&rdquo;. Parts that already finished are not repeated.
      <button type="button" className="thread-dismiss" onClick={onDismiss}>Start a new request instead</button></p>
  </div>;
}
export function workMessage(job: Job): string {
  const result = job.result || {};
  const saved = Number(result.tasks_saved || 0);
  const memories = Number(result.memories_saved || 0);
  const questions = Array.isArray(result.answers) ? result.answers.length : 0;
  if (job.status === "succeeded") {
    const parts = [Number(result.blocks_scheduled) > 0
      ? `${Number(result.blocks_scheduled)} Calendar block(s) created.${saved ? ` ${saved} task(s) also saved.` : ""}`
      : saved || memories ? `Saved ${saved} task(s) and ${memories} memory item(s).` : ""];
    if (questions) parts.push(`Checked ${questions} question(s) against your saved work.`);
    const routines = Array.isArray(result.routines) ? result.routines.filter((item): item is string => typeof item === "string") : [];
    if (routines.length) parts.push(`Saved ${routines.length} routine(s): ${routines.join("; ")}.`);
    return parts.filter(Boolean).join(" ") || "No tasks or facts found in this description.";
  }
  if (["failed", "expired", "cancelled"].includes(job.status)) {
    const message = typeof result.message === "string" ? result.message : job.status === "expired"
      ? "This processing request expired. Your saved results are kept. Check Calendar before submitting a new request."
      : ["intent_unavailable", "provider_unconfigured", "extraction_unavailable", "embedding_unavailable", "answer_unavailable"].includes(job.safe_error || "")
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
  return result.intent === "schedule" || result.intent === "both" ? "Finding a free slot and adding it to Calendar..."
    : result.intent === "question" ? "Looking through your tasks and memories..." : "Understanding and organizing your request...";
}
const ATTACH_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
type Attachment = { name: string; state: "reading" | "done" | "error"; message: string };
/** What a finished document capture saved, in the same words as a typed request. */
export function documentMessage(job: Job, name: string): string {
  const result = job.result || {};
  if (job.status !== "succeeded") return typeof result.message === "string" ? result.message : `Could not finish organizing ${name}. Any saved tasks are kept.`;
  const tasks = Number(result.tasks_saved || 0), memories = Number(result.memories_saved || 0);
  return tasks || memories ? `Saved ${tasks} task(s) and ${memories} memory item(s) from ${name}.` : `Read ${name}, but found no tasks or facts to save.`;
}
export function WorkComposer() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [blocks, setBlocks] = useState<CalendarBlock[]>([]);
  const [defaultDuration, setDefaultDuration] = useState(false);
  const [warning, setWarning] = useState("");
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [issues, setIssues] = useState<string[]>([]);
  const [thread, setThread] = useState<Thread | null>(null);
  const [adjustments, setAdjustments] = useState<string[]>([]);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const controller = useRef<AbortController | null>(null);
  const pending = useRef<{ text: string; key: string; replyTo: string | null } | null>(null);
  const observe = useCallback(async (job: Job, signal: AbortSignal, request = "") => {
    setBusy(true);
    try {
      const finished = await followOrganization(job, current => {
        setMessage(activeOrganization(current) ? workMessage(current) : "");
        setBlocks((current.result?.blocks || []) as CalendarBlock[]);
      }, signal);
      setDefaultDuration(finished.result?.default_duration === true);
      setWarning(typeof finished.result?.warning === "string" ? finished.result.warning : "");
      setAnswers(Array.isArray(finished.result?.answers) ? finished.result.answers as Answer[] : []);
      setAdjustments(finished.status === "succeeded" ? adjustmentNotes(finished.result || {}) : []);
      const questions = finished.subject_id ? openQuestions(finished) : [];
      // Open questions are shown once, in the reply thread, not again as warnings.
      setIssues(finished.status === "succeeded" ? partIssues(finished.result || {}).filter(issue => !questions.includes(issue)) : []);
      setThread(questions.length && finished.subject_id ? { runId: finished.subject_id, request, questions } : null);
      if (finished.status === "succeeded") { setMessage(workMessage(finished)); setText(""); }
      else if (questions.length) { setMessage(""); setText(""); }
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
    const replyTo = thread?.runId ?? null;
    if (!pending.current || pending.current.text !== description || pending.current.replyTo !== replyTo)
      pending.current = { text: description, key: crypto.randomUUID(), replyTo };
    setBusy(true); setError(""); setWarning(""); setBlocks([]); setAnswers([]); setIssues([]); setAdjustments([]); setDefaultDuration(false); setMessage("Understanding your request...");
    controller.current?.abort(); const tracking = new AbortController(); controller.current = tracking;
    try {
      const response = await fetch("/api/commands", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: description, request_key: pending.current.key, ...(replyTo ? { reply_to: replyTo } : {}) }), signal: tracking.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not submit this request.");
      await observe(data.background_job, tracking.signal, thread ? `${thread.request ? `${thread.request}\n` : ""}${description}` : description);
    } catch (cause) { if (!tracking.signal.aborted) { setMessage(""); setError(cause instanceof Error ? cause.message : "Could not submit. Retry the same text."); setBusy(false); } }
  }
  async function attach(file: File) {
    if (!ATTACH_TYPES.includes(file.type)) { setAttachment({ name: file.name, state: "error", message: "Attach a PDF, PNG, JPEG or WebP file." }); return; }
    if (file.size > 3_000_000) { setAttachment({ name: file.name, state: "error", message: "Attach a file of at most 3 MB." }); return; }
    setAttachment({ name: file.name, state: "reading", message: `Reading ${file.name}…` });
    const form = new FormData(); form.set("file", file); form.set("request_key", crypto.randomUUID());
    try {
      const response = await fetch("/api/documents", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not read this document.");
      setAttachment({ name: file.name, state: "reading", message: `Organizing ${file.name}…` });
      const finished = await followOrganization(data.background_job as Job, () => undefined, new AbortController().signal);
      setAttachment({ name: file.name, state: finished.status === "succeeded" ? "done" : "error", message: documentMessage(finished, file.name) });
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (cause) { setAttachment({ name: file.name, state: "error", message: cause instanceof Error ? cause.message : "Could not read this document." }); }
  }
  function pickFile() {
    // Created on demand so the composer stays a single text field until a file is wanted.
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".pdf,image/png,image/jpeg,image/webp";
    input.onchange = () => { const file = input.files?.[0]; if (file) void attach(file); };
    input.click();
  }
  const responding = message || error || warning || blocks.length > 0 || answers.length > 0 || issues.length > 0 || adjustments.length > 0;
  return <section id="composer" className={`composer${busy ? " is-processing" : ""}${thread ? " is-replying" : ""}`} aria-labelledby="composer-heading" aria-busy={busy}>
    <h2 id="composer-heading">{thread ? "FocusOS has a question" : "What is on your mind?"}</h2>
    <p className="section-lede">Write it the way you would say it: one task or a whole list, a question about your saved work, a time to find, or all of it at once.</p>
    {thread && <ReplyThread thread={thread} onDismiss={() => { setThread(null); pending.current = null; }} />}
    <form className="composer-form" onSubmit={event => void submit(event)}>
      <label className="sr-only" htmlFor="work-request">{thread ? "Reply to FocusOS" : "Work or schedule request"}</label>
      <textarea id="work-request" value={text} onChange={event => setText(event.target.value)} rows={thread ? 2 : 6} maxLength={1000} required disabled={busy} aria-describedby="composer-help"
        placeholder={thread ? "yang web" : "Buat task berikut:\n1. Siapkan outline presentasi, deadline 13 Oktober, estimasi 30 menit.\n2. Buat halaman web, deadline 18 Oktober, estimasi 2 jam.\n\nCari waktu besok jam 13-16 untuk belajar selama 30 menit. Kapan deadline review desain?"} />
      <div className="composer-bar">
        {!thread && <button type="button" className="quiet attach" onClick={pickFile} disabled={busy || attachment?.state === "reading"}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M13.5 6.5 7.8 12.2a1.6 1.6 0 0 0 2.3 2.3l6-6a3.2 3.2 0 0 0-4.5-4.5l-6.2 6.2a4.8 4.8 0 0 0 6.8 6.8l4.3-4.3" /></svg>
          Attach a PDF or photo</button>}
        <span className="composer-count" aria-label={`${text.length} of 1000 characters`}>{text.length.toLocaleString()} / 1,000</span>
        <button type="submit" className="button composer-send" disabled={busy || !text.trim()}>{busy ? <><span className="composer-progress" aria-hidden="true" />Working...</> : thread ? "Send reply" : "Send request"}</button>
      </div>
      {attachment && <p role={attachment.state === "error" ? "alert" : "status"} className={`attachment attachment-${attachment.state}`}>{attachment.message}</p>}
      <p id="composer-help" className="composer-help">Indonesian or English. Up to 10 tasks per list. Calendar requests create events automatically. Add a duration, or we use your task estimate or 30 minutes.</p>
    </form>
    {responding && <div className="composer-response">
      {message && <p role="status" aria-live="polite" className="composer-message">{message}</p>}
      {error && <p role="alert" className="composer-message composer-error">{error}</p>}
      {warning && <p role="alert" className="composer-message composer-warning">{warning}</p>}
      {issues.map((issue, index) => <p key={index} role="alert" className="composer-message composer-warning">{issue}</p>)}
      {answers.length > 0 && <ul className="composer-answers" aria-label="Answers from your saved work">{answers.map((item, index) => <li key={index}>
        <span className="composer-question">{item.question}</span>
        {item.status === "answered" && item.answer ? <p className="composer-answer">{item.answer}</p>
          : <p className="composer-answer composer-answer-empty">{item.status === "unavailable" ? "Could not check this question right now. Ask again in a moment." : NO_REFERENCE_NOTE}</p>}
        {item.references.length > 0 && <ul className="composer-references" aria-label="References">{item.references.map((reference, position) => <li key={position}>
          <span className="composer-reference-kind">{REFERENCE_LABEL[reference.kind] ?? "Reference"}</span>
          <strong>{reference.title}</strong>{reference.detail && <small>{reference.detail}</small>}</li>)}</ul>}
      </li>)}</ul>}
      {defaultDuration && blocks.length > 0 && <p className="composer-note">Duration used: 30 minutes.</p>}
      {blocks.length > 0 && adjustments.map((note, index) => <p key={index} className="composer-note">{note}</p>)}
      {blocks.length > 0 && <PaginatedItems as="ul" className="composer-results" label="created Calendar blocks" pageSize={3} items={blocks.map((block, index) => <li key={`${block.start}-${index}`}><strong>{block.title}</strong>
        <span>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: block.timezone }).format(new Date(block.start))} - {new Intl.DateTimeFormat(undefined, { timeStyle: "short", timeZone: block.timezone }).format(new Date(block.end))} ({block.timezone})</span>
        {block.link && <a href={block.link} target="_blank" rel="noopener noreferrer">Open in Google Calendar</a>}</li>)} />}
    </div>}
  </section>;
}
