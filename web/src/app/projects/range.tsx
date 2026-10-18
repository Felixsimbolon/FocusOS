"use client";
import type { CSSProperties } from "react";
import { RIDGE_FAR } from "../art/ridges";
import type { ProjectSummary } from "./projects-panel";

export const MAX_PEAKS = 7;
const BASE = 372, LOW = 300, HIGH = 92;

/** How far up its mountain a project is: the share of its tasks that are done. */
export function progress(project: Pick<ProjectSummary, "open_tasks" | "done_tasks">): number {
  const total = project.open_tasks + project.done_tasks;
  return total ? project.done_tasks / total : 0;
}

/** One peak per project, spread across the width; a project with more work is a taller mountain. */
export function peaks(projects: ProjectSummary[]): { project: ProjectSummary; x: number; y: number; climbed: number }[] {
  const shown = projects.slice(0, MAX_PEAKS), step = 1440 / (shown.length + 1);
  return shown.map((project, index) => {
    const work = Math.min(1, (project.open_tasks + project.done_tasks) / 12);
    return { project, x: step * (index + 1), y: LOW - (LOW - HIGH) * (0.35 + 0.65 * work) + (index % 2 ? 18 : 0), climbed: progress(project) };
  });
}

export function rangePath(points: { x: number; y: number }[]): string {
  if (!points.length) return "M0 340 C360 320 1080 320 1440 340 L1440 420 L0 420 Z";
  let path = `M0 ${BASE - 20}`;
  points.forEach((point, index) => {
    const before = index ? (points[index - 1].x + point.x) / 2 : point.x / 2;
    const valley = index ? Math.max(points[index - 1].y, point.y) + 70 : BASE - 20;
    path += ` L${before.toFixed(0)} ${Math.min(BASE, valley).toFixed(0)} L${(point.x - 14).toFixed(0)} ${(point.y + 6).toFixed(0)}`
      + ` L${point.x.toFixed(0)} ${point.y.toFixed(0)} L${(point.x + 16).toFixed(0)} ${(point.y + 8).toFixed(0)}`;
  });
  return `${path} L1440 ${BASE - 10} L1440 420 L0 420 Z`;
}

export function Range({ projects }: { projects: ProjectSummary[] }) {
  const points = peaks(projects);
  return <div className="range">
    <svg className="range-art" viewBox="0 0 1440 420" preserveAspectRatio="none" aria-hidden="true">
      <path className="ridge ridge-far" d={RIDGE_FAR} />
      <path className="ridge ridge-mid range-mountains" d={rangePath(points)} />
      {points.map(({ project, x, y, climbed }, index) => {
        // The route up the left face; the lit part is the share of tasks already done.
        const startX = x - 120, startY = Math.min(BASE, y + 150);
        return <g key={project.id} className="range-climb" style={{ animationDelay: `${0.5 + index * 0.12}s` }}>
          <path className="range-route" d={`M${startX} ${startY} L${x} ${y}`} />
          {climbed > 0 && <path className="range-done" d={`M${startX} ${startY} L${startX + (x - startX) * climbed} ${startY + (y - startY) * climbed}`} />}
        </g>;
      })}
      <path className="ridge ridge-near" d="M0 396 C240 384 520 380 760 388 C1000 396 1220 398 1440 390 L1440 420 L0 420 Z" />
    </svg>
    {points.map(({ project, x, y, climbed }, index) => <a key={project.id} className="range-peak" href={`/projects/${project.id}`}
      style={{ left: `${(x / 1440) * 100}%`, top: `${(y / 420) * 100}%`, animationDelay: `${0.7 + index * 0.12}s` } as CSSProperties}>
      <span className="range-name">{project.name}</span>
      <small>{project.open_tasks + project.done_tasks ? `${Math.round(climbed * 100)}% done` : "no tasks yet"}</small>
    </a>)}
  </div>;
}
