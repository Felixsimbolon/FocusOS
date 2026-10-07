"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { DeadlineCalendar, deadlineDay } from "./deadline-calendar";

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

  const renderTask = (task: Task) => (
    <li key={task.id}>
      <div className="task-list-title">
        <strong>{task.title}</strong>
        <span className={"task-priority priority-" + task.priority}>{task.priority}</span>
      </div>
      {task.description ? <p>{task.description}</p> : null}
      {task.project_id ? (
        <p className="task-project">
          Project: {projects.find((project) => project.id === task.project_id)?.name ?? "Project"}
        </p>
      ) : null}
      {task.source_id ? <a href={"/activity?source=" + task.source_id}>View source evidence</a> : null}
      <div className="task-meta">
        {readableDue(task, timezone) ? <span>Due {readableDue(task, timezone)}</span> : null}
        {task.estimate_minutes ? <span>{task.estimate_minutes} min estimate</span> : null}
      </div>
      {editingTaskId === task.id ? (
        <form className="task-edit-form" onSubmit={(event) => void saveTitle(event, task)}>
          <label>
            Edit task title
            <input
              value={editTitle}
              onChange={(event) => setEditTitle(event.target.value)}
              maxLength={200}
              required
              autoFocus
            />
          </label>
          <div className="task-actions">
            <button type="submit" disabled={updatingTaskId === task.id}>Save changes</button>
            <button type="button" onClick={() => setEditingTaskId(null)}>Cancel</button>
          </div>
        </form>
      ) : (
        <div className="task-actions">
          <button
            type="button"
            onClick={() => {
              setEditingTaskId(task.id);
              setEditTitle(task.title);
            }}
            disabled={updatingTaskId === task.id}
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => void patchTask(task, { status: "done" })}
            disabled={updatingTaskId === task.id}
          >
            Mark complete
          </button>
        </div>
      )}
    </li>
  );

  return (
    <section className="task-board" aria-labelledby="tasks-heading">
      <div className="task-board-heading">
        <div>
          <h2 id="tasks-heading">Today</h2>
          <p>{todayContext || "Tasks due today or earlier, plus tasks without a deadline."}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            void refresh();
            void loadProjects();
          }}
          disabled={loading}
        >
          {loading ? "Loading…" : "Reload tasks"}
        </button>
      </div>

      {error ? <p className="task-error" role="alert">{error}</p> : null}
      {message ? <p className="task-message" role="status">{message}</p> : null}

      {loading ? (
        <p>Loading tasks…</p>
      ) : tasks.length ? (
        <ul className="task-list">
          {tasks.map(renderTask)}
        </ul>
      ) : (
        <p className="task-empty">No tasks due today or earlier, or without a deadline.</p>
      )}
      {loading ? <p>Loading deadlines…</p> :
        <DeadlineCalendar tasks={upcomingTasks} timezone={timezone} today={today}
          renderTask={renderTask} truncated={taskListTruncated} />}
    </section>
  );
}
