"use client";
import { LOCALE } from "../locale";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { type Job } from "../jobs/client";
import { followOrganization } from "../organization";
import { NotesPanel } from "../notes/notes-panel";
import { RIDGE_FAR } from "../art/ridges";
import { AssignmentFlow, type Assignment } from "./assignment-flow";
import { STATUS_LABEL } from "./projects-panel";

type Task = { id: string; title: string; status: string; priority: string; due_kind: string; due_date: string | null; due_at: string | null; estimate_minutes: number | null; version: number };
type Block = { id: string; title: string; start: string; end: string; timezone: string };
export type ProjectDetail = { id: string; name: string; deadline: string | null; tasks: Task[]; notes: { id: string; title: string; updated_at: string }[];
  assignments: { id: string; title: string; status: string }[]; upcoming: Block[] };
type Answer = { question: string; status: string; answer: string | null; references: { kind: string; title: string; detail?: string }[] };

const DAY = 86_400_000;
const strip = (title: string, project: string) => title.startsWith(`[${project}] `) ? title.slice(project.length + 3) : title;
export const dueOf = (task: Task) => task.due_kind === "date" ? task.due_date : task.due_at ? task.due_at.slice(0, 10) : null;

/** The trail climbs from today (left) to the project's last deadline (the summit, right). */
const TRAIL = { left: 96, right: 1236, base: 344, rise: 196 };
export function trailPoint(t: number): [number, number] {
  const c = Math.min(1, Math.max(0, t));
  return [TRAIL.left + (TRAIL.right - TRAIL.left) * c, TRAIL.base - TRAIL.rise * Math.pow(c, 1.35) + 7 * Math.sin(c * Math.PI * 6) * (1 - c)];
}
/** Where a date sits on the trail: 0 today, 1 the summit; with no deadline the trail spans two weeks. */
export function trailT(date: string, today: string, summit: string | null): number {
  const start = Date.parse(`${today}T00:00:00Z`), end = summit ? Date.parse(`${summit}T00:00:00Z`) : start + 14 * DAY;
  return end <= start ? 1 : Math.min(1, Math.max(0, (Date.parse(`${date.slice(0, 10)}T00:00:00Z`) - start) / (end - start)));
}
function trailPath(): string {
  return Array.from({ length: 81 }, (_, i) => trailPoint(i / 80)).map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
}
export function daysLeft(today: string, summit: string | null): number | null {
  return summit ? Math.round((Date.parse(`${summit}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / DAY) : null;
}

function Trail({ detail, today }: { detail: ProjectDetail; today: string }) {
  const path = trailPath();
  const [sx, sy] = trailPoint(1);
  const mountain = `M0 372 L${TRAIL.left} ${TRAIL.base} ${path.replace(/^M[^L]+/, "")} L${sx + 40} ${sy + 6} C1330 ${sy + 60} 1390 300 1440 312 L1440 420 L0 420 Z`;
  const dated = detail.tasks.filter(task => task.status === "open" && dueOf(task));
  return <svg className="trail-art" viewBox="0 0 1440 420" preserveAspectRatio="xMidYMax slice" role="img"
    aria-label={detail.deadline ? `A trail from today to the deadline on ${detail.deadline}` : "A trail of the next two weeks"}>
    <path className="ridge ridge-far" d={RIDGE_FAR} />
    <path className="ridge ridge-mid" d={mountain} />
    <path className="trail" d={path} pathLength={1} />
    {dated.map((task, index) => { const [x, y] = trailPoint(trailT(dueOf(task)!, today, detail.deadline));
      return <g key={task.id} className={`trail-flag${task.priority === "high" ? " is-high" : ""}`} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`} style={{ animationDelay: `${1.1 + index * 0.06}s` }}>
        <title>{`${strip(task.title, detail.name)}, due ${dueOf(task)}`}</title><path className="flag-pole" d="M0 0 V-26" /><path className="flag-cloth" d="M0 -26 L16 -21 L0 -16 Z" /></g>; })}
    {detail.upcoming.map((block, index) => { const [x, y] = trailPoint(trailT(block.start, today, detail.deadline));
      return <circle key={block.id} className="trail-block" cx={x} cy={y} r="8" style={{ animationDelay: `${1.3 + index * 0.08}s` }}>
        <title>{`${strip(block.title, detail.name)}, ${block.start.slice(0, 16).replace("T", " ")}`}</title></circle>; })}
    <g className="trail-ends"><circle cx={TRAIL.left} cy={TRAIL.base} r="6" /><circle className="summit" cx={sx} cy={sy} r="9" /></g>
    <path className="ridge ridge-near" d="M0 392 C200 378 420 372 640 380 C860 388 1100 394 1440 384 L1440 420 L0 420 Z" />
  </svg>;
}

function Ask({ project }: { project: string }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [error, setError] = useState("");
  async function ask(event: FormEvent) {
    event.preventDefault(); if (!question.trim() || busy) return;
    setBusy(true); setError(""); setAnswers([]);
    // Naming the project lets the answer use this project's notes.
    const text = question.toLowerCase().includes(project.toLowerCase()) ? question.trim() : `${question.trim()} (proyek ${project})`;
    try {
      const response = await fetch("/api/commands", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, request_key: crypto.randomUUID() }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not ask right now.");
      const finished = await followOrganization(data.background_job as Job, () => undefined, new AbortController().signal);
      const found = Array.isArray(finished.result?.answers) ? finished.result.answers as Answer[] : [];
      if (!found.length) setError(typeof finished.result?.message === "string" ? finished.result.message : "That did not read as a question. Try asking it directly.");
      setAnswers(found);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not ask right now."); }
    finally { setBusy(false); }
  }
  return <section className="project-ask" aria-labelledby="ask-heading">
    <h2 id="ask-heading">Ask about {project}</h2>
    <form onSubmit={event => void ask(event)}>
      <label className="sr-only" htmlFor="project-question">Question about this project</label>
      <textarea id="project-question" rows={2} value={question} maxLength={600} placeholder="Apa yang harus ada di laporan?" onChange={event => setQuestion(event.target.value)} />
      <button type="submit" className="button" disabled={busy || !question.trim()}>{busy ? "Lookingâ€¦" : "Ask"}</button>
    </form>
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {answers.map((answer, index) => <div key={index} className="project-answer">
      <p className="composer-answer">{answer.status === "answered" && answer.answer ? answer.answer : "No reference found in this project's notes, tasks or your other saved work."}</p>
      {answer.references.length > 0 && <ul className="composer-references">{answer.references.map((reference, position) => <li key={position}>
        <span className="composer-reference-kind">{reference.kind === "note" ? "Note" : reference.kind === "task" ? "Task" : reference.kind === "event" ? "Calendar" : "Memory"}</span><strong>{reference.title}</strong></li>)}</ul>}
    </div>)}
  </section>;
}

export function ProjectView({ id, initial, timezone }: { id: string; initial: ProjectDetail | null; timezone: string }) {
  const [detail, setDetail] = useState<ProjectDetail | null>(initial);
  const [today] = useState(() => new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date()));
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => {
    fetch(`/api/projects/${id}`, { cache: "no-store" }).then(response => response.ok ? response.json() : null).then(result => { if (result) setDetail(result); }).catch(() => undefined);
  }, [id]);
  useEffect(() => {
    if (!initial) load();
    window.addEventListener("focusos:tasks-changed", load);
    window.addEventListener("focusos:schedule-changed", load);
    return () => { window.removeEventListener("focusos:tasks-changed", load); window.removeEventListener("focusos:schedule-changed", load); };
  }, [initial, load]);
  async function complete(task: Task) {
    setBusy(task.id);
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(task.id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: task.version, status: "done" }) });
      if (response.ok) { window.dispatchEvent(new Event("focusos:tasks-changed")); }
    } finally { setBusy(null); }
  }
  async function openAssignment(assignmentId: string) {
    const response = await fetch(`/api/assignments/${assignmentId}`, { cache: "no-store" });
    if (response.ok) setAssignment(await response.json() as Assignment);
  }
  if (!detail) return <div className="ground"><p className="loading-line" style={{ paddingTop: "8rem" }}>Loading projectâ€¦</p></div>;
  const open = detail.tasks.filter(task => task.status === "open"), done = detail.tasks.length - open.length;
  const left = daysLeft(today, detail.deadline);
  const when = (value: string, zone: string) => new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(value));
  return <>
    <section className="trail-hero" aria-labelledby="project-heading">
      <Trail detail={detail} today={today} />
      <div className="trail-text">
        <a className="trail-back" href="/#projects">All projects</a>
        <h1 id="project-heading">{detail.name}</h1>
        <p className="horizon-status">{open.length} open {open.length === 1 ? "task" : "tasks"}{done ? ` and ${done} done` : ""}, {detail.upcoming.length} focus {detail.upcoming.length === 1 ? "block" : "blocks"} booked.
          {left === null ? " No deadline yet: the trail shows the next two weeks." : left > 0 ? ` ${left} ${left === 1 ? "day" : "days"} to the last deadline, ${detail.deadline}.` : left === 0 ? " The last deadline is today." : " The last deadline has passed."}</p>
        <p className="trail-legend"><span className="legend-block">Focus blocks</span><span className="legend-flag">Task deadlines</span><span className="legend-summit">Last deadline</span></p>
      </div>
    </section>
    <div className="ground project-ground">
      <div className="project-main">
        <section aria-labelledby="project-notes-heading">
          <h2 id="project-notes-heading">Notes</h2>
          <p className="section-lede">Everything you write here belongs to {detail.name}. When you ask about this project, these notes are part of the answer.</p>
          <NotesPanel projectId={detail.id} />
        </section>
      </div>
      <aside className="project-side">
        <Ask project={detail.name} />
        <section aria-labelledby="project-tasks-heading">
          <h2 id="project-tasks-heading">Tasks</h2>
          {open.length ? <ul className="task-list">{open.map(task => <li key={task.id} className={`task priority-${task.priority}${busy === task.id ? " is-busy" : ""}`}>
            <button type="button" className="task-check" onClick={() => void complete(task)} disabled={busy === task.id} aria-label={`Mark complete: ${task.title}`}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M6 10.5l2.6 2.6L14 7.6" /></svg></button>
            <div className="task-body"><p className="task-title">{strip(task.title, detail.name)}</p>
              <p className="task-details">{[dueOf(task) ? `due ${dueOf(task)}` : null, task.estimate_minutes ? `${task.estimate_minutes} min` : null].filter(Boolean).join(", ")}</p></div>
          </li>)}</ul> : <p className="quiet-line">No open tasks. Write one in the box on Home and mention {detail.name}.</p>}
        </section>
        <section aria-labelledby="project-upcoming-heading">
          <h2 id="project-upcoming-heading">Coming up</h2>
          {detail.upcoming.length ? <ul className="plain-list">{detail.upcoming.map(block => <li key={block.id}><span>{strip(block.title, detail.name)}</span><small>{when(block.start, block.timezone)}</small></li>)}</ul>
            : <p className="quiet-line">No focus blocks booked for this project.</p>}
        </section>
        <section aria-labelledby="project-assignments-heading">
          <h2 id="project-assignments-heading">Assignments</h2>
          {detail.assignments.length ? <ul className="plain-list">{detail.assignments.map(item => <li key={item.id}><span>{item.title}</span>
            <button type="button" className="quiet" onClick={() => void openAssignment(item.id)}>{STATUS_LABEL[item.status] ?? item.status}</button></li>)}</ul>
            : <p className="quiet-line">None yet. Analyse a brief from the Projects section on Home.</p>}
        </section>
      </aside>
    </div>
    {assignment && <div className="ground"><AssignmentFlow key={assignment.id} initial={assignment} projects={[{ id: detail.id, name: detail.name }]} onClose={() => setAssignment(null)} onChanged={load} /></div>}
  </>;
}
