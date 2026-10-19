"use client";
import { LOCALE } from "../locale";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AssignmentFlow, type Assignment } from "./assignment-flow";

export type ProjectSummary = { id: string; name: string; open_tasks: number; done_tasks: number; notes: number; assignments: number; files?: number;
  next_deadline: string | null; next_block: { title: string; start: string; timezone: string } | null };

const when = (value: string, zone: string) => new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(value));

export function projectLine(project: ProjectSummary): string {
  const parts = [`${project.open_tasks} open ${project.open_tasks === 1 ? "task" : "tasks"}`];
  if (project.next_deadline) parts.push(`next deadline ${project.next_deadline}`);
  if (project.notes) parts.push(`${project.notes} ${project.notes === 1 ? "note" : "notes"}`);
  if (project.assignments) parts.push(`${project.assignments} ${project.assignments === 1 ? "assignment" : "assignments"}`);
  if (project.files) parts.push(`${project.files} ${project.files === 1 ? "file" : "files"}`);
  return parts.join(", ");
}

export const STATUS_LABEL: Record<string, string> = { transcribed: "Belum dianalisis", questions: "Menunggu jawabanmu", planned: "Sudah direncanakan" };

/** The project list with its actions; on the Projects page it starts from server data and reports changes upward. */
export function ProjectsPanel({ initial, onProjects }: { initial?: ProjectSummary[] | null; onProjects?: (projects: ProjectSummary[]) => void } = {}) {
  const [projects, setProjects] = useState<ProjectSummary[]>(initial ?? []);
  const skipFirst = useRef(!!initial);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [flow, setFlow] = useState<{ assignment: Assignment | null } | null>(null);
  const load = useCallback(() => {
    fetch("/api/projects/overview", { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error()))
      .then(result => { const list = Array.isArray(result) ? result : []; setProjects(list); onProjects?.(list); setError(""); })
      .catch(() => setError("Projects are unavailable right now."));
  }, [onProjects]);
  useEffect(() => {
    if (skipFirst.current) skipFirst.current = false; else load();
    window.addEventListener("focusos:tasks-changed", load);
    return () => window.removeEventListener("focusos:tasks-changed", load);
  }, [load]);
  async function add(event: FormEvent) {
    event.preventDefault(); if (!name.trim()) return;
    const response = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    if (!response.ok) { setError("Could not add this project."); return; }
    setName(""); load();
  }
  return <div className="projects">
    <div className="projects-actions">
      <button type="button" className="button" onClick={() => setFlow({ assignment: null })}>Analisis tugas dari file</button>
      <form className="add-project" onSubmit={event => void add(event)}>
        <label className="sr-only" htmlFor="project-name">Project name</label>
        <input id="project-name" value={name} maxLength={100} placeholder="Nama proyek, misalnya Skripsi" onChange={event => setName(event.target.value)} />
        <button type="submit" disabled={!name.trim()}>Add project</button>
      </form>
    </div>
    {flow && <AssignmentFlow key={flow.assignment?.id ?? "new"} initial={flow.assignment} projects={projects} onClose={() => setFlow(null)} onChanged={load} />}
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {projects.length ? <ul className="project-list">{projects.map(project => <li key={project.id}>
      <a className="project-row" href={`/projects/${project.id}`}>
        <span className="project-name">{project.name}</span><span className="project-meta">{projectLine(project)}</span>
        {project.next_block && <span className="project-next">Next: {project.next_block.title.replace(/^\[[^\]]*\]\s*/, "")}, {when(project.next_block.start, project.next_block.timezone)}</span>}
      </a>
    </li>)}</ul> : !error && <p className="quiet-line">No projects yet. Add one above, or analyse an assignment and FocusOS will create its project.</p>}
  </div>;
}
