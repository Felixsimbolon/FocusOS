"use client";
import { useState } from "react";
import { ProjectsPanel, type ProjectSummary } from "./projects-panel";
import { MAX_PEAKS, Range } from "./range";

export function rangeStatus(projects: ProjectSummary[]): string {
  if (!projects.length) return "No projects yet. Add one below, or analyse an assignment brief and FocusOS will create its project.";
  const open = projects.reduce((sum, project) => sum + project.open_tasks, 0);
  const soon = projects.map(project => project.next_deadline).filter((date): date is string => !!date).sort()[0];
  return `${projects.length} ${projects.length === 1 ? "project" : "projects"}, ${open} open ${open === 1 ? "task" : "tasks"}${soon ? `, the next deadline on ${soon}` : ""}.`
    + (projects.length > MAX_PEAKS ? ` The range shows the first ${MAX_PEAKS}; every project is listed below.` : "");
}

/** The Projects page: every project as a mountain, then the full list. */
export function ProjectsIndex({ initial }: { initial: ProjectSummary[] | null }) {
  const [projects, setProjects] = useState<ProjectSummary[]>(initial ?? []);
  return <>
    <section className="range-hero" aria-labelledby="projects-page-heading">
      <div className="range-text">
        <h1 id="projects-page-heading">Projects</h1>
        <p className="horizon-status">{rangeStatus(projects)}</p>
      </div>
      <Range projects={projects} />
    </section>
    <div className="ground">
      <section aria-labelledby="all-projects-heading">
        <h2 id="all-projects-heading">All projects</h2>
        <p className="section-lede">Open one to see its schedule, notes and files. Each route up a peak lights up as its tasks are done.</p>
        <ProjectsPanel initial={initial} onProjects={setProjects} />
      </section>
    </div>
  </>;
}
