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
  project_id: string | null;
  version: number;
};

type Project = { id: string; name: string; created_at: string };
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
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectSaving, setProjectSaving] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [projectMessage, setProjectMessage] = useState("");
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

  const loadProjects = useCallback(async () => {
    setProjectError("");
    try {
      const response = await fetch("/api/projects", { cache: "no-store" });
      const result = (await response.json()) as { projects?: Project[] };
      if (!response.ok || !Array.isArray(result.projects)) {
        setProjectError("Projects could not be loaded. You can still create tasks without one.");
        return;
      }
      setProjects(result.projects);
    } catch {
      setProjectError("Projects could not be loaded. You can still create tasks without one.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    void loadProjects();
  }, [loadProjects, refresh]);

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProjectSaving(true);
    setProjectError("");
    setProjectMessage("");
    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: projectName }),
      });
      const result = (await response.json()) as {
        error?: string;
        existing?: boolean;
        project?: Project;
      };
      if (!response.ok || !result.project) {
        setProjectError(result.error ?? "Project could not be saved.");
        return;
      }
      const saved = result.project;
      setProjects((current) =>
        [saved, ...current.filter((item) => item.id !== saved.id)]
          .sort((left, right) => left.name.localeCompare(right.name))
          .slice(0, 100),
      );
      setSelectedProjectId(saved.id);
      setProjectName("");
      setProjectMessage(result.existing ? "That project already exists; it is selected." : "Project saved.");
    } catch {
      setProjectError("Project could not be saved. Please try again.");
    } finally {
      setProjectSaving(false);
    }
  }

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
    const projectId = String(values.get("project_id") ?? "");
    const task = {
      title,
      description: description || null,
      priority: String(values.get("priority") ?? "normal"),
      due_kind: dueDate ? "date" : "none",
      project_id: projectId || null,
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
            Project
            <select
              name="project_id"
              value={selectedProjectId}
              onChange={(event) => setSelectedProjectId(event.target.value)}
            >
              <option value="">No project</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
          </label>
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

      <form className="project-form" onSubmit={createProject}>
        <label>
          New project
          <input
            type="text"
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
            maxLength={100}
            required
            placeholder="Project name"
          />
        </label>
        <button type="submit" disabled={projectSaving}>
          {projectSaving ? "Saving…" : "Add project"}
        </button>
      </form>
      {projectError ? <p className="task-error" role="alert">{projectError}</p> : null}
      {projectMessage ? <p className="task-message" role="status">{projectMessage}</p> : null}
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
              {task.project_id ? (
                <p className="task-project">
                  Project: {projects.find((project) => project.id === task.project_id)?.name ?? "Project"}
                </p>
              ) : null}
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
