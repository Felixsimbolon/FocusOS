"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { PaginatedItems } from "../paginated-items";
import type { Task } from "./task-board";

const priorityRank: Record<Task["priority"], number> = { high: 0, normal: 1, low: 2 };
const DAYS = 7;

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

export function addDays(key: string, days: number): string {
  const date = new Date(`${key}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function format(key: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(new Date(`${key}T12:00:00Z`));
}

/** A week of upcoming deadlines as a ribbon of days; pick a day to see what is due. */
export function DeadlineCalendar({ tasks, timezone, today, renderTask, truncated }: {
  tasks: Task[]; timezone: string; today: string; renderTask: (task: Task) => ReactNode; truncated: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { setOffset(0); setSelected(null); }, [today]);

  const byDay = useMemo(() => {
    const grouped = new Map<string, Task[]>();
    for (const task of tasks) {
      const key = deadlineDay(task, timezone);
      if (key) grouped.set(key, [...(grouped.get(key) ?? []), task]);
    }
    for (const list of grouped.values()) list.sort((a, b) => priorityRank[a.priority] - priorityRank[b.priority] || a.title.localeCompare(b.title));
    return grouped;
  }, [tasks, timezone]);
  const first = addDays(today, 1 + offset * DAYS);
  const days = Array.from({ length: DAYS }, (_, index) => addDays(first, index));
  const later = tasks.filter(task => (deadlineDay(task, timezone) ?? "") > days[days.length - 1]).length;
  const active = selected ?? days.find(day => byDay.has(day)) ?? null;
  const activeTasks = active ? byDay.get(active) ?? [] : [];

  return <section className="coming-up" aria-labelledby="deadline-heading">
    <div className="section-head">
      <h2 id="deadline-heading">Coming up</h2>
      <div className="ribbon-nav">
        <button type="button" className="quiet" aria-label="Earlier week" disabled={offset === 0} onClick={() => { setOffset(offset - 1); setSelected(null); }}>Earlier</button>
        <button type="button" className="quiet" aria-label="Later week" onClick={() => { setOffset(offset + 1); setSelected(null); }}>Later</button>
      </div>
    </div>
    <p className="section-lede">{tasks.length ? `${tasks.length} open ${tasks.length === 1 ? "task has" : "tasks have"} a deadline after today.` : "Nothing is due after today yet."}
      {later ? ` ${later} more after ${format(days[days.length - 1], { month: "short", day: "numeric" })}.` : ""}</p>
    {truncated ? <p className="notice">Showing the first 100 open tasks. Some deadlines may not appear.</p> : null}
    <ol className="ribbon" aria-label={`Deadlines from ${format(days[0], { month: "long", day: "numeric" })}`}>
      {days.map(day => {
        const due = byDay.get(day) ?? [];
        const weekend = [0, 6].includes(new Date(`${day}T12:00:00Z`).getUTCDay());
        return <li key={day}>
          <button type="button" className={`ribbon-day${due.length ? " has-due" : ""}${active === day ? " is-active" : ""}${weekend ? " is-weekend" : ""}`}
            aria-pressed={active === day} onClick={() => setSelected(day)}
            aria-label={`${format(day, { weekday: "long", month: "long", day: "numeric" })}${due.length ? `, ${due.length} task${due.length === 1 ? "" : "s"} due` : ", nothing due"}`}>
            <span className="ribbon-weekday">{format(day, { weekday: "narrow" })}</span>
            <span className="ribbon-date">{format(day, { day: "numeric" })}</span>
            <span className="ribbon-marks" aria-hidden="true">{due.slice(0, 3).map(task => <i key={task.id} className={`mark-${task.priority}`} />)}</span>
          </button>
        </li>;
      })}
    </ol>
    <div className="ribbon-detail" aria-live="polite">
      {active ? <>
        <p className="ribbon-detail-day">{format(active, { weekday: "long", month: "long", day: "numeric" })}</p>
        {activeTasks.length ? <PaginatedItems key={active} as="ul" className="task-list" items={activeTasks.map(renderTask)} pageSize={4} label="tasks on this date" />
          : <p className="quiet-line">Nothing is due on this day.</p>}
      </> : <p className="quiet-line">Pick a day to see what is due.</p>}
    </div>
  </section>;
}
