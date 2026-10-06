"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import type { Task } from "./task-board";
import { filterTasks, PAGE_SIZE, taskEditPayload } from "./workspace-model";

type Project = { id: string; name: string };
export function TaskWorkspace() {
  const [tasks, setTasks] = useState<Task[]>([]),
    [projects, setProjects] = useState<Project[]>([]);
  const [status, setStatus] = useState("open"),
    [query, setQuery] = useState(""),
    [project, setProject] = useState(""),
    [priority, setPriority] = useState("");
  const [page, setPage] = useState(0),
    [editing, setEditing] = useState<Task | null>(null);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [truncated, setTruncated] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/tasks?status=${status}`, {
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok || !Array.isArray(result.tasks))
        throw new Error("Tasks could not be loaded. Try again.");
      setTasks(result.tasks);
      setTruncated(result.truncated);
      setPage(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tasks unavailable.");
    } finally {
      setBusy(false);
    }
  }, [status]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    fetch("/api/projects", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((r) => {
        if (r?.projects) setProjects(r.projects);
      })
      .catch(() => {});
  }, []);
  const visible = filterTasks(tasks, query, project, priority);
  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  async function update(task: Task, changes: Record<string, unknown>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`/api/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: task.version, ...changes }),
      });
      if (response.status === 409) {
        await load();
        setEditing(null);
        throw new Error(
          "This task changed elsewhere. Review the refreshed version before saving again.",
        );
      }
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          result.error ||
            "Update could not be confirmed. Reload before retrying.",
        );
      setEditing(null);
      await load();
      setNotice(
        "Task saved. Existing Calendar events are unchanged; manage them in Schedule.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Task unavailable.");
    } finally {
      setBusy(false);
    }
  }
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!editing) return;
    try {
      await update(
        editing,
        taskEditPayload(editing, new FormData(e.currentTarget)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check your task fields.");
    }
  }
  return (
    <section className="workspace">
      <div className="workspace-toolbar">
        <label>
          Search
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            placeholder="Title or description"
          />
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Active</option>
            <option value="done">Completed</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <label>
          Priority
          <select
            value={priority}
            onChange={(e) => {
              setPriority(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All priorities</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label>
          Project
          <select
            value={project}
            onChange={(e) => {
              setProject(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {truncated && (
        <p>
          Showing the first 100 tasks in this status. Export includes a larger
          bounded dataset.
        </p>
      )}
      <p aria-live="polite">
        {busy
          ? "Loading..."
          : `${visible.length} tasks ? urgency, then deadline`}
      </p>
      {visible.length === 0 && !busy && (
        <div className="review-panel">
          <h2>Nothing here yet</h2>
          <p>Add a task from Today or organize an email in Activity.</p>
          <a href="/">Add a task</a>
        </div>
      )}
      <div className="workspace-list">
        {visible
          .slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
          .map((task) => (
            <article className="review-card" key={task.id}>
              <div className="workspace-task-heading">
                <h2>{task.title}</h2>
                <span className="task-priority">{task.priority}</span>
              </div>
              {task.description && <p>{task.description}</p>}
              <p>
                {task.due_kind === "none"
                  ? "No deadline"
                  : task.due_date || `${task.due_at} (${task.due_timezone})`}
                {task.estimate_minutes ? ` ? ${task.estimate_minutes} min` : ""}
              </p>
              {task.source_id && (
                <a href={`/activity?source=${task.source_id}`}>View evidence</a>
              )}
              <div className="workspace-actions">
                <button
                  disabled={busy}
                  onClick={() => {
                    setEditing(task);
                    setError("");
                  }}
                >
                  Edit
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void update(task, {
                      status: task.status === "open" ? "done" : "open",
                    })
                  }
                >
                  {task.status === "open" ? "Complete" : "Reopen"}
                </button>
                {task.status !== "archived" && (
                  <button
                    disabled={busy}
                    onClick={() => void update(task, { status: "archived" })}
                  >
                    Archive
                  </button>
                )}
              </div>
            </article>
          ))}
      </div>
      {pages > 1 && (
        <nav className="workspace-actions" aria-label="Task pages">
          <button disabled={current === 0} onClick={() => setPage(current - 1)}>
            Previous
          </button>
          <span>
            {current + 1} / {pages}
          </span>
          <button
            disabled={current + 1 >= pages}
            onClick={() => setPage(current + 1)}
          >
            Next
          </button>
        </nav>
      )}
      {editing && (
        <form className="review-panel" onSubmit={save} key={editing.id}>
          <h2>Edit task</h2>
          <label>
            Title
            <input
              name="title"
              required
              maxLength={200}
              defaultValue={editing.title}
            />
          </label>
          <label>
            Description
            <textarea
              name="description"
              maxLength={2000}
              defaultValue={editing.description || ""}
            />
          </label>
          <label>
            Priority
            <select name="priority" defaultValue={editing.priority}>
              <option>high</option>
              <option>normal</option>
              <option>low</option>
            </select>
          </label>
          <label>
            Estimate (minutes)
            <input
              name="estimate"
              type="number"
              min={1}
              max={1440}
              defaultValue={editing.estimate_minutes || ""}
            />
          </label>
          <label>
            Project
            <select name="project_id" defaultValue={editing.project_id || ""}>
              <option value="">No project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Deadline type
            <select name="due_kind" defaultValue={editing.due_kind}>
              <option value="none">No deadline</option>
              <option value="date">Date only</option>
              <option value="datetime">Exact date and time</option>
            </select>
          </label>
          <label>
            Date
            <input
              name="due_date"
              type="date"
              defaultValue={editing.due_date || ""}
            />
          </label>
          <label>
            ISO timestamp with offset
            <input
              name="due_at"
              defaultValue={editing.due_at || ""}
              placeholder="2026-10-12T17:00:00+07:00"
            />
          </label>
          <label>
            IANA timezone
            <input
              name="due_timezone"
              defaultValue={editing.due_timezone || "Asia/Jakarta"}
            />
          </label>
          <div className="workspace-actions">
            <button disabled={busy} type="submit">
              Save changes
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              Cancel edit
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
