"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Task } from "./task-board";

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const priorityRank: Record<Task["priority"], number> = { high: 0, normal: 1, low: 2 };

export function deadlineDay(task: Pick<Task, "due_kind" | "due_date" | "due_at">, timezone: string): string | null {
  if (task.due_kind === "date") return task.due_date;
  if (task.due_kind !== "datetime" || !task.due_at) return null;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(task.due_at));
  const part = (type: string) => parts.find(item => item.type === type)?.value;
  const year = part("year"), month = part("month"), day = part("day");
  return year && month && day ? `${year}-${month}-${day}` : null;
}

function monthLabel(month: string, timezone: string): string {
  const [year, number] = month.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: timezone })
    .format(new Date(Date.UTC(year, number - 1, 15)));
}

function moveMonth(month: string, direction: number): string {
  const [year, number] = month.split("-").map(Number);
  const next = new Date(Date.UTC(year, number - 1 + direction, 1));
  return `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, "0")}`;
}

function dateLabel(key: string): string {
  return new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${key}T12:00:00Z`));
}

export function DeadlineCalendar({ tasks, timezone, today, renderTask, truncated }: {
  tasks: Task[]; timezone: string; today: string; renderTask: (task: Task) => ReactNode; truncated: boolean;
}) {
  const [month, setMonth] = useState(today.slice(0, 7));
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  useEffect(() => { setMonth(today.slice(0, 7)); }, [today]);

  const byDay = useMemo(() => {
    const grouped = new Map<string, Task[]>();
    for (const task of tasks) {
      const key = deadlineDay(task, timezone);
      if (key) grouped.set(key, [...(grouped.get(key) ?? []), task]);
    }
    return grouped;
  }, [tasks, timezone]);
  const ordered = useMemo(() => [...tasks].sort((a, b) => {
    const left = deadlineDay(a, timezone) ?? "9999-12-31";
    const right = deadlineDay(b, timezone) ?? "9999-12-31";
    const leftTime = a.due_at ? Date.parse(a.due_at) : Number.NEGATIVE_INFINITY;
    const rightTime = b.due_at ? Date.parse(b.due_at) : Number.NEGATIVE_INFINITY;
    return priorityRank[a.priority] - priorityRank[b.priority]
      || left.localeCompare(right)
      || (leftTime < rightTime ? -1 : leftTime > rightTime ? 1 : 0)
      || a.title.localeCompare(b.title);
  }), [tasks, timezone]);
  const pageCount = Math.max(1, Math.ceil(ordered.length / 2));
  const currentPage = Math.min(page, pageCount);
  useEffect(() => { setPage(previous => Math.min(previous, pageCount)); }, [pageCount]);
  const visibleTasks = ordered.slice((currentPage - 1) * 2, currentPage * 2);
  const [year, number] = month.split("-").map(Number);
  const firstWeekday = (new Date(Date.UTC(year, number - 1, 1)).getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const activeDay = hovered ?? selected;
  const activeTasks = activeDay ? byDay.get(activeDay) ?? [] : [];

  return <section className="deadline-section" aria-labelledby="deadline-heading">
    <div className="deadline-heading">
      <div><span className="section-eyebrow">YOUR TIMELINE</span><h2 id="deadline-heading">Deadlines</h2>
        <p>A clear view of what is due next. Red dates have open tasks.</p></div>
      <span className="deadline-count">{tasks.length} upcoming</span>
    </div>
    <div className="deadline-layout">
      <div className="deadline-calendar" aria-label="Deadline calendar">
        <div className="deadline-calendar-nav">
          <div><span className="section-eyebrow">CALENDAR</span><h3>{monthLabel(month, timezone)}</h3></div>
          <div className="deadline-nav-actions">
            <button type="button" aria-label="Previous month" onClick={() => { setMonth(moveMonth(month, -1)); setHovered(null); }}>‹</button>
            <button type="button" aria-label="Go to current month" className="deadline-today" onClick={() => { setMonth(today.slice(0, 7)); setHovered(null); }}>Today</button>
            <button type="button" aria-label="Next month" onClick={() => { setMonth(moveMonth(month, 1)); setHovered(null); }}>›</button>
          </div>
        </div>
        <div className="deadline-grid" aria-label={monthLabel(month, timezone)}>
          {weekdays.map(day => <span className="deadline-weekday" key={day}>{day}</span>)}
          {Array.from({ length: firstWeekday }, (_, index) => <span className="deadline-empty" key={`before-${index}`} />)}
          {Array.from({ length: daysInMonth }, (_, index) => {
            const key = `${month}-${String(index + 1).padStart(2, "0")}`;
            const count = byDay.get(key)?.length ?? 0;
            return <button key={key} type="button" className={`deadline-day${count ? " has-deadline" : ""}${today === key ? " is-today" : ""}${activeDay === key ? " is-active" : ""}`}
              aria-label={`${dateLabel(key)}${count ? `, ${count} task${count === 1 ? "" : "s"} due` : ", no tasks due"}`}
              aria-pressed={selected === key} onClick={() => setSelected(key)}
              onMouseEnter={() => setHovered(key)} onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(key)} onBlur={() => setHovered(null)}>
              <span>{index + 1}</span>{count ? <i aria-hidden="true" /> : null}
            </button>;
          })}
        </div>
        <div className="deadline-day-preview" aria-live="polite">
          {activeDay ? <><strong>{dateLabel(activeDay)}</strong>{activeTasks.length ?
            <ul>{activeTasks.map(task => <li key={task.id}>{task.title}</li>)}</ul> : <p>No open task due on this date.</p>}</>
            : <p>Hover over or select a date to see its tasks.</p>}
        </div>
      </div>
      <div className="deadline-list-panel">
        <div className="deadline-list-heading"><span className="section-eyebrow">COMING UP</span><h3>Deadline list</h3></div>
        {truncated ? <p className="deadline-notice">Showing the first 100 open tasks. Some deadlines may not appear.</p> : null}
        {ordered.length ? <ul className="task-list deadline-task-list">{visibleTasks.map(renderTask)}</ul> :
          <p className="task-empty">Nothing due later. Your next deadline will appear here.</p>}
        {pageCount > 1 ? <nav className="deadline-pagination" aria-label="Deadline pages">
          <button type="button" onClick={() => setPage(currentPage - 1)} disabled={currentPage === 1}>Previous</button>
          <span>Page {currentPage} of {pageCount}</span>
          <button type="button" onClick={() => setPage(currentPage + 1)} disabled={currentPage === pageCount}>Next</button>
        </nav> : null}
      </div>
    </div>
  </section>;
}