"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { PaginatedItems } from "../paginated-items";
import { DeadlineCalendar, deadlineDay } from "./deadline-calendar";
import { KiteField } from "../art/spots";

export type Task = {
  id: string;
  title: string;
  description: string | null;
  status: "open" | "done" | "archived";
  priority: "low" | "normal" | "high";
  due_kind: "none" | "date" | "datetime";
  due_date: string | null;
  due_at: string | null;
  due_timezone: string | null;
  estimate_minutes: number | null;
  project_id: string | null;
  source_id?: string | null;
  version: number;
};

type Project = { id: string; name: string; created_at: string };
type TaskList = {
  tasks: Task[];
  truncated: boolean;
  today?: string;
  timezone?: string;
};

function readableDue(task: Task, timezone: string): string | null {
  if (task.due_kind === "date" && task.due_date) return task.due_date;
  if (task.due_kind === "datetime" && task.due_at) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone || task.due_timezone || undefined,
    }).format(new Date(task.due_at));
  }
  return null;
}

export function TaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [upcomingTasks, setUpcomingTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [todayContext, setTodayContext] = useState("");
  const [today, setToday] = useState(() => new Date().toISOString().slice(0, 10));
  const [timezone, setTimezone] = useState("Asia/Jakarta");
  const [taskListTruncated, setTaskListTruncated] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [updatingTaskId, setUpdatingTaskId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [response, openResponse] = await Promise.all([
        fetch("/api/tasks/today", { cache: "no-store" }),
        fetch("/api/tasks?status=open", { cache: "no-store" }),
      ]);
      const [result, openResult] = await Promise.all([
        response.json() as Promise<TaskList | { error?: string }>,
        openResponse.json() as Promise<TaskList | { error?: string }>,
      ]);
      if (!response.ok || !openResponse.ok || !("tasks" in result) || !("tasks" in openResult)) {
        setError("Tasks could not be loaded. Please try again.");
        return;
      }
      setTasks(result.tasks);
      const taskTimezone = result.timezone ?? "Asia/Jakarta";
      const currentDay = result.today ?? new Date().toISOString().slice(0, 10);
      setUpcomingTasks(openResult.tasks.filter((task) => {
        const due = deadlineDay(task, taskTimezone);
        return due !== null && due > currentDay;
      }));
      setToday(currentDay);
      setTimezone(taskTimezone);
      setTaskListTruncated(openResult.truncated);
      setTodayContext(
        result.today && result.timezone
          ? "Showing tasks due on or before " + result.today + " in " + result.timezone + "."
          : "",
      );
      setMessage(result.truncated || openResult.truncated ? "Showing the first 100 matching tasks. Older tasks may not appear." : "");
    } catch {
      setError("Tasks could not be loaded. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      const response = await fetch("/api/projects", { cache: "no-store" });
      const result = (await response.json()) as { projects?: Project[] };
      if (!response.ok || !Array.isArray(result.projects)) {
        return;
      }
      setProjects(result.projects);
    } catch {
      // Existing project names are optional context for saved tasks.
    }
  }, []);

  useEffect(() => {
    void refresh();
    void loadProjects();
    const listener = () => { void refresh(); };
    window.addEventListener("focusos:tasks-changed", listener);
    return () => window.removeEventListener("focusos:tasks-changed", listener);
  }, [loadProjects, refresh]);

  async function patchTask(task: Task, changes: Record<string, unknown>) {
    setUpdatingTaskId(task.id);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/tasks/" + encodeURIComponent(task.id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: task.version, ...changes }),
      });
      if (response.status === 409) {
        await refresh();
        setError("This task changed elsewhere. The latest Today list is loaded; review it before editing again.");
        setEditingTaskId(null);
        return;
      }
      const result = (await response.json()) as { error?: string; task?: Task };
      if (!response.ok || !result.task) {
        setError(result.error ?? "Task could not be updated.");
        return;
      }
      setEditingTaskId(null);
      await refresh();
      setMessage(changes.status === "done" ? "Task completed." : "Task updated.");
    } catch {
      setError("Task update could not be confirmed. Reload the latest task state.");
    } finally {
      setUpdatingTaskId(null);
    }
  }

  async function saveTitle(event: FormEvent<HTMLFormElement>, task: Task) {
    event.preventDefault();
    await patchTask(task, { title: editTitle });
  }

  const projectName = (task: Task) => task.project_id ? projects.find((project) => project.id === task.project_id)?.name ?? "Project" : null;
  const renderTask = (task: Task) => {
    const due = readableDue(task, timezone);
    const details = [due ? `due ${due}` : null, task.estimate_minutes ? `${task.estimate_minutes} min` : null, projectName(task)].filter(Boolean).join(", ");
    const busy = updatingTaskId === task.id;
    return <li key={task.id} className={`task priority-${task.priority}${busy ? " is-busy" : ""}`}>
      <button type="button" className="task-check" onClick={() => void patchTask(task, { status: "done" })} disabled={busy}
        aria-label={`Mark complete: ${task.title}`} title="Mark complete">
        <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M6 10.5l2.6 2.6L14 7.6" /></svg>
      </button>
      {editingTaskId === task.id ? (
        <form className="task-edit" onSubmit={(event) => void saveTitle(event, task)}>
          <label className="sr-only" htmlFor={`edit-${task.id}`}>Edit task title</label>
          <input id={`edit-${task.id}`} value={editTitle} onChange={(event) => setEditTitle(event.target.value)} maxLength={200} required autoFocus />
          <button type="submit" disabled={busy}>Save changes</button>
          <button type="button" className="quiet" onClick={() => setEditingTaskId(null)}>Cancel</button>
        </form>
      ) : (
        <div className="task-body">
          <p className="task-title">{task.title}{task.priority === "high" && <span className="task-flag">High priority</span>}</p>
          {details && <p className="task-details">{details}</p>}
          {task.description ? <p className="task-description">{task.description}</p> : null}
        </div>
      )}
      {editingTaskId !== task.id && <button type="button" className="task-edit-button quiet" disabled={busy}
        onClick={() => { setEditingTaskId(task.id); setEditTitle(task.title); }}>Edit</button>}
    </li>;
  };

  return (
    <section className="today" aria-labelledby="tasks-heading">
      <div className="today-list">
        <div className="section-head">
          <h2 id="tasks-heading">Today</h2>
          <button type="button" className="quiet" onClick={() => { void refresh(); void loadProjects(); }} disabled={loading}>
            {loading ? "Loading…" : "Reload"}
          </button>
        </div>
        <p className="section-lede">{todayContext || "Tasks due today or earlier, plus tasks without a deadline."}</p>
        {error ? <p className="notice notice-error" role="alert">{error}</p> : null}
        {message ? <p className="notice" role="status">{message}</p> : null}
        {loading ? <p className="loading-line">Loading tasks…</p> : tasks.length ? (
          <PaginatedItems as="ul" className="task-list" items={tasks.map(renderTask)} pageSize={6} label="today tasks" />
        ) : (
          <div className="empty"><KiteField /><p>Nothing is due today. Write a task above, or enjoy the open field.</p></div>
        )}
      </div>
      {loading ? null : <DeadlineCalendar tasks={upcomingTasks} timezone={timezone} today={today}
        renderTask={renderTask} truncated={taskListTruncated} />}
    </section>
  );
}
