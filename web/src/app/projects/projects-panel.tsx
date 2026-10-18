"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AssignmentFlow, type Assignment } from "./assignment-flow";

export type ProjectSummary = { id: string; name: string; open_tasks: number; done_tasks: number; notes: number; assignments: number;
  next_deadline: string | null; next_block: { title: string; start: string; timezone: string } | null };
type Detail = { id: string; name: string; tasks: { id: string; title: string; status: string; due_date: string | null; due_at: string | null; estimate_minutes: number | null }[];
  notes: { id: string; title: string; updated_at: string }[]; assignments: { id: string; title: string; status: string }[];
  upcoming: { id: string; title: string; start: string; end: string; timezone: string }[] };

const when = (value: string, zone: string) => new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(value));

export function projectLine(project: ProjectSummary): string {
  const parts = [`${project.open_tasks} open ${project.open_tasks === 1 ? "task" : "tasks"}`];
  if (project.next_deadline) parts.push(`next deadline ${project.next_deadline}`);
  if (project.notes) parts.push(`${project.notes} ${project.notes === 1 ? "note" : "notes"}`);
  if (project.assignments) parts.push(`${project.assignments} ${project.assignments === 1 ? "assignment" : "assignments"}`);
  return parts.join(", ");
}

export const STATUS_LABEL: Record<string, string> = { transcribed: "Belum dianalisis", questions: "Menunggu jawabanmu", planned: "Sudah direncanakan" };

function ProjectDetail({ id, onOpenAssignment }: { id: string; onOpenAssignment: (assignmentId: string) => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  useEffect(() => {
    fetch(`/api/projects/${id}`, { cache: "no-store" }).then(response => response.ok ? response.json() : null).then(setDetail).catch(() => setDetail(null));
  }, [id]);
  if (!detail) return <p className="loading-line">Loading project…</p>;
  const open = detail.tasks.filter(task => task.status === "open"), done = detail.tasks.length - open.length;
  return <div className="project-detail">
    <div><h4>Tasks</h4>{open.length ? <ul className="plain-list">{open.slice(0, 12).map(task => <li key={task.id}><span>{task.title}</span>
      <small>{[task.due_date || task.due_at?.slice(0, 10), task.estimate_minutes ? `${task.estimate_minutes} min` : null].filter(Boolean).join(", ")}</small></li>)}</ul>
      : <p className="quiet-line">No open tasks.</p>}{done > 0 && <p className="quiet-line">{done} done.</p>}</div>
    <div><h4>Coming up</h4>{detail.upcoming.length ? <ul className="plain-list">{detail.upcoming.map(block => <li key={block.id}><span>{block.title}</span><small>{when(block.start, block.timezone)}</small></li>)}</ul>
      : <p className="quiet-line">No focus blocks booked.</p>}</div>
    <div><h4>Assignments</h4>{detail.assignments.length ? <ul className="plain-list">{detail.assignments.map(item => <li key={item.id}><span>{item.title}</span>
      <button type="button" className="quiet" onClick={() => onOpenAssignment(item.id)}>{STATUS_LABEL[item.status] ?? item.status}</button></li>)}</ul>
      : <p className="quiet-line">None yet.</p>}</div>
    <div><h4>Notes</h4>{detail.notes.length ? <ul className="plain-list">{detail.notes.map(note => <li key={note.id}>
      <button type="button" className="quiet" onClick={() => window.dispatchEvent(new CustomEvent("focusos:open-note", { detail: { id: note.id } }))}>{note.title}</button></li>)}</ul>
      : <p className="quiet-line">No notes for this project.</p>}</div>
  </div>;
}

export function ProjectsPanel() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [flow, setFlow] = useState<{ assignment: Assignment | null } | null>(null);
  const load = useCallback(() => {
    fetch("/api/projects/overview", { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error()))
      .then(result => { setProjects(Array.isArray(result) ? result : []); setError(""); })
      .catch(() => setError("Projects are unavailable right now."));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("focusos:tasks-changed", load);
    return () => window.removeEventListener("focusos:tasks-changed", load);
  }, [load]);
  async function add(event: FormEvent) {
    event.preventDefault(); if (!name.trim()) return;
    const response = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    if (!response.ok) { setError("Could not add this project."); return; }
    setName(""); load();
  }
  async function openAssignment(id: string) {
    const response = await fetch(`/api/assignments/${id}`, { cache: "no-store" });
    if (response.ok) setFlow({ assignment: await response.json() as Assignment });
  }
  return <div className="projects">
    <div className="projects-actions">
      <button type="button" className="button" onClick={() => setFlow({ assignment: null })}>Analisis tugas dari PDF</button>
      <form className="add-project" onSubmit={event => void add(event)}>
        <label className="sr-only" htmlFor="project-name">Project name</label>
        <input id="project-name" value={name} maxLength={100} placeholder="Nama proyek, misalnya Skripsi" onChange={event => setName(event.target.value)} />
        <button type="submit" disabled={!name.trim()}>Add project</button>
      </form>
    </div>
    {flow && <AssignmentFlow key={flow.assignment?.id ?? "new"} initial={flow.assignment} projects={projects} onClose={() => setFlow(null)} onChanged={load} />}
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {projects.length ? <ul className="project-list">{projects.map(project => <li key={project.id} className={open === project.id ? "is-open" : ""}>
      <button type="button" className="project-row" aria-expanded={open === project.id} onClick={() => setOpen(open === project.id ? null : project.id)}>
        <span className="project-name">{project.name}</span><span className="project-meta">{projectLine(project)}</span>
        {project.next_block && <span className="project-next">Next: {project.next_block.title.replace(/^\[[^\]]*\]\s*/, "")}, {when(project.next_block.start, project.next_block.timezone)}</span>}
      </button>
      {open === project.id && <ProjectDetail id={project.id} onOpenAssignment={id => void openAssignment(id)} />}
    </li>)}</ul> : !error && <p className="quiet-line">No projects yet. Add one above, or analyse an assignment and FocusOS will create its project.</p>}
  </div>;
}
