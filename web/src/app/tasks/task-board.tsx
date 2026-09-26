"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Task = {
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
  version: number;
};

type TaskList = { tasks: Task[]; truncated: boolean };

function readableDue(task: Task): string | null {
  if (task.due_kind === "date" && task.due_date) return task.due_date;
  if (task.due_kind === "datetime" && task.due_at) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: task.due_timezone ?? undefined,
    }).format(new Date(task.due_at));
  }
  return null;
}

export function TaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pendingRequest, setPendingRequest] = useState<{
    id: string;
    payload: string;
  } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/tasks?status=open&limit=100", {
        cache: "no-store",
      });
      const result = (await response.json()) as TaskList | { error?: string };
      if (!response.ok || !("tasks" in result)) {
        setError("Tasks could not be loaded. Please try again.");
        return;
      }
      setTasks(result.tasks);
      setMessage(result.truncated ? "Showing the first 100 open tasks." : "");
    } catch {
      setError("Tasks could not be loaded. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    const form = event.currentTarget;
    const values = new FormData(form);
    const title = String(values.get("title") ?? "").trim();
    const description = String(values.get("description") ?? "").trim();
    const dueDate = String(values.get("due_date") ?? "");
    const estimate = String(values.get("estimate_minutes") ?? "");
    const task = {
      title,
      description: description || null,
      priority: String(values.get("priority") ?? "normal"),
      due_kind: dueDate ? "date" : "none",
      ...(dueDate ? { due_date: dueDate } : {}),
      ...(estimate ? { estimate_minutes: Number(estimate) } : {}),
    };
    const payload = JSON.stringify(task);
    const requestId =
      pendingRequest?.payload === payload ? pendingRequest.id : crypto.randomUUID();
    setPendingRequest({ id: requestId, payload });

    try {
      const response = await fetch("/api/tasks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": requestId,
        },
        body: payload,
      });
      const result = (await response.json()) as { error?: string; task?: Task };
      if (!response.ok || !result.task) {
        setError(result.error ?? "Task could not be saved.");
        if (response.status < 500) setPendingRequest(null);
        return;
      }
      form.reset();
      setPendingRequest(null);
      await refresh();
      setMessage("Task saved.");
    } catch {
      setError("The save result is unknown. Retry the same details to avoid creating a duplicate.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="task-board" aria-labelledby="tasks-heading">
      <div className="task-board-heading">
        <div>
          <h2 id="tasks-heading">Open tasks</h2>
          <p>Add a task, then reload the list to confirm it is saved.</p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Loading…" : "Reload tasks"}
        </button>
      </div>

      <form className="task-form" onSubmit={create}>
        <label>
          Task
          <input name="title" type="text" maxLength={200} required placeholder="What needs to get done?" />
        </label>
        <label>
          Details
          <textarea name="description" maxLength={2000} rows={3} placeholder="Optional context" />
        </label>
        <div className="task-form-row">
          <label>
            Priority
            <select name="priority" defaultValue="normal">
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
          </label>
          <label>
            Due date
            <input name="due_date" type="date" />
          </label>
          <label>
            Estimate (minutes)
            <input name="estimate_minutes" type="number" min={1} max={1440} step={1} />
          </label>
        </div>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Add task"}
        </button>
      </form>

      {error ? <p className="task-error" role="alert">{error}</p> : null}
      {message ? <p className="task-message" role="status">{message}</p> : null}

      {loading ? (
        <p>Loading tasks…</p>
      ) : tasks.length ? (
        <ul className="task-list">
          {tasks.map((task) => (
            <li key={task.id}>
              <div className="task-list-title">
                <strong>{task.title}</strong>
                <span className={"task-priority priority-" + task.priority}>{task.priority}</span>
              </div>
              {task.description ? <p>{task.description}</p> : null}
              <div className="task-meta">
                {readableDue(task) ? <span>Due {readableDue(task)}</span> : null}
                {task.estimate_minutes ? <span>{task.estimate_minutes} min estimate</span> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="task-empty">No open tasks yet.</p>
      )}
    </section>
  );
}
