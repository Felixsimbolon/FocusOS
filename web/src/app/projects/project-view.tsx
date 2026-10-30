"use client";
import { LOCALE } from "../locale";
import { FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { DOCX, FILE_ACCEPT, FILE_KINDS, MAX_FILE_BYTES, fileType } from "@/lib/files";
import { type Job } from "../jobs/client";
import { followOrganization } from "../organization";
import { NotesPanel } from "../notes/notes-panel";
import { RIDGE_FAR } from "../art/ridges";
import { AssignmentFlow, type Assignment } from "./assignment-flow";
import { STATUS_LABEL } from "./projects-panel";

type Task = { id: string; title: string; status: string; priority: string; due_kind: string; due_date: string | null; due_at: string | null; estimate_minutes: number | null; version: number };
type Block = { id: string; title: string; start: string; end: string; timezone: string };
export type ProjectDetail = { id: string; name: string; deadline: string | null; tasks: Task[]; notes: { id: string; title: string; updated_at: string }[];
  assignments: { id: string; title: string; status: string }[]; upcoming: Block[]; past: Block[]; files: ProjectFile[] };
export type ProjectFile = { id: string; name: string; mime_type: string; size_bytes: number; created_at: string; assignment_id: string | null; assignment: string | null };
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
      <button type="submit" className="button" disabled={busy || !question.trim()}>{busy ? "Looking…" : "Ask"}</button>
    </form>
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {answers.map((answer, index) => <div key={index} className="project-answer">
      <p className="composer-answer">{answer.status === "answered" && answer.answer ? answer.answer : "No reference found in this project's notes, tasks or your other saved work."}</p>
      {answer.references.length > 0 && <ul className="composer-references">{answer.references.map((reference, position) => <li key={position}>
        <span className="composer-reference-kind">{reference.kind === "note" ? "Note" : reference.kind === "task" ? "Task" : reference.kind === "event" ? "Calendar" : "Memory"}</span><strong>{reference.title}</strong></li>)}</ul>}
    </div>)}
  </section>;
}

export const TABS = [{ id: "overview", label: "Overview" }, { id: "schedule", label: "Schedule" }, { id: "notes", label: "Notes" }, { id: "files", label: "Files" }] as const;
type TabId = typeof TABS[number]["id"];
export const tabFromHash = (hash: string): TabId => TABS.find(tab => `#${tab.id}` === hash)?.id ?? "overview";

const localDate = (value: string, zone: string) => new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(new Date(value));
const clock = (value: string, zone: string) => new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: zone }).format(new Date(value));
type AgendaItem = { id: string; kind: "block" | "deadline"; title: string; time: string | null; sort: string };

/** Booked focus blocks and open deadlines from today on, grouped by local day, soonest first. */
export function agenda(detail: Pick<ProjectDetail, "name" | "tasks" | "upcoming">, today: string): { date: string; items: AgendaItem[] }[] {
  const days = new Map<string, AgendaItem[]>();
  const add = (date: string, item: AgendaItem) => days.set(date, [...(days.get(date) ?? []), item]);
  for (const block of detail.upcoming) add(localDate(block.start, block.timezone), { id: block.id, kind: "block", title: strip(block.title, detail.name),
    time: `${clock(block.start, block.timezone)}–${clock(block.end, block.timezone)}`, sort: block.start });
  for (const task of detail.tasks) {
    const due = dueOf(task);
    if (task.status !== "open" || !due || due < today) continue;
    add(due, { id: task.id, kind: "deadline", title: strip(task.title, detail.name), time: null, sort: "~" + task.title }); // "~" sorts after any time, so a day lists its blocks first
  }
  return [...days.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, items]) => ({ date, items: items.sort((a, b) => a.sort < b.sort ? -1 : a.sort > b.sort ? 1 : 0) }));
}

export function fileSize(bytes: number): string {
  return bytes < 1_000_000 ? `${Math.max(1, Math.round(bytes / 1000))} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
}

function Schedule({ detail, today }: { detail: ProjectDetail; today: string }) {
  const days = agenda(detail, today);
  const dayName = (date: string) => new Intl.DateTimeFormat(LOCALE, { weekday: "long", timeZone: "UTC" }).format(new Date(`${date}T12:00:00Z`));
  const dayDate = (date: string) => new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${date}T12:00:00Z`));
  return <div className="project-schedule">
    {days.length ? <ol className="agenda">{days.map(day => <li key={day.date} className="agenda-day">
      <h3><span>{day.date === today ? "Today" : dayName(day.date)}</span><small>{dayDate(day.date)}</small></h3>
      <ul>{day.items.map(item => <li key={item.id} className={`agenda-item is-${item.kind}`}>
        <span className="agenda-time">{item.kind === "block" ? item.time : "Due"}</span><span className="agenda-title">{item.title}</span></li>)}</ul>
    </li>)}</ol>
      : <p className="quiet-line">Nothing booked and no deadlines ahead. Ask on Home to find focus time for a {detail.name} task.</p>}
    {detail.past.length > 0 && <details className="drawer">
      <summary><span>Earlier focus blocks</span><small>{detail.past.length}</small></summary>
      <ul className="plain-list drawer-body">{detail.past.map(block => <li key={block.id}><span>{strip(block.title, detail.name)}</span>
        <small>{dayDate(localDate(block.start, block.timezone))}, {clock(block.start, block.timezone)}</small></li>)}</ul>
    </details>}
  </div>;
}

function FileGlyph({ mime }: { mime: string }) {
  // Pages of text for documents (PDF, Word, Markdown); a landscape for photos.
  const pdf = mime === "application/pdf" || mime === DOCX || mime.startsWith("text/");
  return <svg className={`file-glyph${pdf ? " is-pdf" : " is-image"}`} viewBox="0 0 32 40" aria-hidden="true">
    <path className="file-sheet" d="M3 1h18l8 8v28a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2z" /><path className="file-fold" d="M21 1v8h8" />
    {pdf ? <><path className="file-line" d="M7 18h18M7 23h18M7 28h12" /></>
      : <><circle className="file-sun" cx="11" cy="17" r="3" /><path className="file-hill" d="M3 33l8-9 6 6 4-4 8 7v2H3z" /></>}
  </svg>;
}

function Files({ detail, onChanged }: { detail: ProjectDetail; onChanged: () => void }) {
  const [uploading, setUploading] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [over, setOver] = useState(false);
  const picker = useRef<HTMLInputElement | null>(null);
  async function upload(file: File) {
    if (!fileType(file)) { setNotice(`Add a ${FILE_KINDS} file.`); return; }
    if (file.size > MAX_FILE_BYTES) { setNotice("This file is larger than 3 MB. Compress it or split it first."); return; }
    setUploading(file.name); setNotice("");
    const form = new FormData(); form.append("id", crypto.randomUUID()); form.append("file", file);
    try {
      const response = await fetch(`/api/projects/${detail.id}/files`, { method: "POST", body: form });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || "Could not keep this file.");
      onChanged();
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : "Could not keep this file."); }
    finally { setUploading(null); if (picker.current) picker.current.value = ""; }
  }
  async function open(id: string) {
    // Open the tab now, while the click still counts, then point it at the short-lived link.
    const tab = window.open("about:blank", "_blank");
    try {
      const response = await fetch(`/api/files/${id}`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok || typeof result.url !== "string") throw new Error(result.error || "This file cannot be opened right now.");
      if (tab) { tab.opener = null; tab.location.href = result.url; } else window.location.href = result.url;
    } catch (cause) { tab?.close(); setNotice(cause instanceof Error ? cause.message : "This file cannot be opened right now."); }
  }
  async function remove(id: string, name: string) {
    if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;
    const response = await fetch(`/api/files/${id}`, { method: "DELETE" });
    if (response.ok) onChanged(); else setNotice("Could not delete this file.");
  }
  const added = (value: string) => new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
  return <div className={`project-files${over ? " is-over" : ""}`}
    onDragOver={event => { event.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
    onDrop={event => { event.preventDefault(); setOver(false); const file = event.dataTransfer.files[0]; if (file) void upload(file); }}>
    <div className="files-add">
      <button type="button" className="button" onClick={() => picker.current?.click()} disabled={!!uploading}>Add a file</button>
      <input ref={picker} type="file" hidden accept={FILE_ACCEPT} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
      <p className="quiet-line">PDF, Word, Markdown or a photo, up to 3 MB. You can also drop a file anywhere here. Briefs you analyse for this project appear here too.</p>
    </div>
    {notice && <p role="alert" className="notice notice-error">{notice}</p>}
    <ul className="file-list">
      {uploading && <li className="file-row is-uploading"><FileGlyph mime="application/pdf" /><div><p className="file-name">{uploading}</p><small>Keeping this file…</small></div></li>}
      {detail.files.map(file => <li key={file.id} className="file-row">
        <FileGlyph mime={file.mime_type} />
        <div><button type="button" className="file-name" onClick={() => void open(file.id)}>{file.name}</button>
          <small>{[fileSize(file.size_bytes), `added ${added(file.created_at)}`, file.assignment ? `brief for ${file.assignment}` : null].filter(Boolean).join(", ")}</small></div>
        <button type="button" className="quiet" onClick={() => void remove(file.id, file.name)}>Delete</button>
      </li>)}
    </ul>
    {!detail.files.length && !uploading && <p className="quiet-line">No files yet. Keep the brief, the rubric or your lecture slides here so they are one click away.</p>}
  </div>;
}

export function ProjectView({ id, initial, timezone }: { id: string; initial: ProjectDetail | null; timezone: string }) {
  const [detail, setDetail] = useState<ProjectDetail | null>(initial);
  const [today] = useState(() => new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date()));
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("overview");
  const load = useCallback(() => {
    fetch(`/api/projects/${id}`, { cache: "no-store" }).then(response => response.ok ? response.json() : null).then(result => { if (result) setDetail(result); }).catch(() => undefined);
  }, [id]);
  useEffect(() => {
    if (!initial) load();
    setTab(tabFromHash(window.location.hash));
    const onHash = () => setTab(tabFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    window.addEventListener("focusos:tasks-changed", load);
    window.addEventListener("focusos:schedule-changed", load);
    return () => { window.removeEventListener("hashchange", onHash); window.removeEventListener("focusos:tasks-changed", load); window.removeEventListener("focusos:schedule-changed", load); };
  }, [initial, load]);
  function choose(next: TabId) {
    setTab(next);
    window.history.replaceState(null, "", next === "overview" ? window.location.pathname : `#${next}`);
  }
  function onTabKey(event: KeyboardEvent<HTMLDivElement>) {
    const index = TABS.findIndex(item => item.id === tab);
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TABS[(index + step + TABS.length) % TABS.length].id;
    choose(next); document.getElementById(`tab-${next}`)?.focus();
  }
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
  if (!detail) return <div className="ground"><p className="loading-line" style={{ paddingTop: "8rem" }}>Loading project…</p></div>;
  const open = detail.tasks.filter(task => task.status === "open"), done = detail.tasks.length - open.length;
  const left = daysLeft(today, detail.deadline);
  const counts: Record<TabId, number | null> = { overview: null, schedule: detail.upcoming.length, notes: detail.notes.length, files: detail.files.length };
  const when = (value: string, zone: string) => new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(value));
  return <>
    <section className="trail-hero" aria-labelledby="project-heading">
      <Trail detail={detail} today={today} />
      <div className="trail-text">
        <a className="trail-back" href="/projects">All projects</a>
        <h1 id="project-heading">{detail.name}</h1>
        <p className="horizon-status">{open.length} open {open.length === 1 ? "task" : "tasks"}{done ? ` and ${done} done` : ""}, {detail.upcoming.length} focus {detail.upcoming.length === 1 ? "block" : "blocks"} booked.
          {left === null ? " No deadline yet: the trail shows the next two weeks." : left > 0 ? ` ${left} ${left === 1 ? "day" : "days"} to the last deadline, ${detail.deadline}.` : left === 0 ? " The last deadline is today." : " The last deadline has passed."}</p>
        <p className="trail-legend"><span className="legend-block">Focus blocks</span><span className="legend-flag">Task deadlines</span><span className="legend-summit">Last deadline</span></p>
      </div>
    </section>
    <div className="project-tabs-bar">
      <div className="project-tabs" role="tablist" aria-label={`${detail.name} sections`} onKeyDown={onTabKey}>
        {TABS.map(item => <button key={item.id} id={`tab-${item.id}`} type="button" role="tab" aria-selected={tab === item.id} aria-controls={`panel-${item.id}`}
          tabIndex={tab === item.id ? 0 : -1} onClick={() => choose(item.id)}>{item.label}{counts[item.id] ? <small>{counts[item.id]}</small> : null}</button>)}
      </div>
    </div>
    <div className="ground project-ground">
      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} key={tab} className="project-panel">
        {tab === "overview" && <div className="project-overview">
          <section aria-labelledby="project-tasks-heading">
            <h2 id="project-tasks-heading">Tasks</h2>
            {open.length ? <ul className="task-list">{open.map(task => <li key={task.id} className={`task priority-${task.priority}${busy === task.id ? " is-busy" : ""}`}>
              <button type="button" className="task-check" onClick={() => void complete(task)} disabled={busy === task.id} aria-label={`Mark complete: ${task.title}`}>
                <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M6 10.5l2.6 2.6L14 7.6" /></svg></button>
              <div className="task-body"><p className="task-title">{strip(task.title, detail.name)}</p>
                <p className="task-details">{[dueOf(task) ? `due ${dueOf(task)}` : null, task.estimate_minutes ? `${task.estimate_minutes} min` : null].filter(Boolean).join(", ")}</p></div>
            </li>)}</ul> : <p className="quiet-line">No open tasks. Write one in the box on Home and mention {detail.name}.</p>}
            {detail.upcoming[0] && <p className="project-next">Next focus block: {strip(detail.upcoming[0].title, detail.name)}, {when(detail.upcoming[0].start, detail.upcoming[0].timezone)}</p>}
          </section>
          <aside className="project-side">
            <Ask project={detail.name} />
            <section aria-labelledby="project-assignments-heading">
              <h2 id="project-assignments-heading">Assignments</h2>
              {detail.assignments.length ? <ul className="plain-list">{detail.assignments.map(item => <li key={item.id}><span>{item.title}</span>
                <button type="button" className="quiet" onClick={() => void openAssignment(item.id)}>{STATUS_LABEL[item.status] ?? item.status}</button></li>)}</ul>
                : <p className="quiet-line">None yet. Analyse a brief from the Projects page.</p>}
            </section>
          </aside>
        </div>}
        {tab === "schedule" && <Schedule detail={detail} today={today} />}
        {tab === "notes" && <>
          <p className="section-lede">Everything you write here belongs to {detail.name}. When you ask about this project, these notes are part of the answer.</p>
          <NotesPanel projectId={detail.id} />
        </>}
        {tab === "files" && <Files detail={detail} onChanged={load} />}
      </div>
    </div>
    {assignment && <div className="ground"><AssignmentFlow key={assignment.id} initial={assignment} projects={[{ id: detail.id, name: detail.name }]} onClose={() => setAssignment(null)} onChanged={load}
      tasks={detail.tasks} blocks={[...detail.past, ...detail.upcoming]} /></div>}
  </>;
}
