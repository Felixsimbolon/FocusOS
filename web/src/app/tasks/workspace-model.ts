import type { Task } from "./task-board";

export const PAGE_SIZE = 12;
export function filterTasks(tasks: Task[], query: string, project: string, priority: string) {
  const needle = query.trim().toLocaleLowerCase();
  return tasks.filter(task => (!needle || `${task.title} ${task.description || ""}`.toLocaleLowerCase().includes(needle))
    && (!project || task.project_id === project) && (!priority || task.priority === priority))
    .sort((a, b) => ({ high: 0, normal: 1, low: 2 }[a.priority] - { high: 0, normal: 1, low: 2 }[b.priority])
      || (a.due_date || a.due_at || "9999").localeCompare(b.due_date || b.due_at || "9999") || a.id.localeCompare(b.id));
}
export function taskEditPayload(task: Task, values: FormData) {
  const kind = String(values.get("due_kind"));
  const title = String(values.get("title") || "").trim();
  const estimate = String(values.get("estimate") || "").trim();
  if (!title || title.length > 200) throw new Error("Enter a title of 1-200 characters.");
  if (estimate && (!/^\d+$/.test(estimate) || Number(estimate) < 1 || Number(estimate) > 1440)) throw new Error("Estimate must be 1-1440 minutes.");
  if (!["none", "date", "datetime"].includes(kind)) throw new Error("Choose a deadline type.");
  const dueDate = String(values.get("due_date") || "");
  const dueAt = String(values.get("due_at") || "");
  const zone = String(values.get("due_timezone") || "").trim();
  if (kind === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) throw new Error("Choose a deadline date.");
  if (kind === "datetime" && (!zone || !/(Z|[+-]\d{2}:\d{2})$/.test(dueAt) || Number.isNaN(Date.parse(dueAt)))) throw new Error("Enter an ISO timestamp with offset and an IANA timezone.");
  return { expected_version: task.version, title, description: String(values.get("description") || "").trim() || null,
    priority: String(values.get("priority")), estimate_minutes: estimate ? Number(estimate) : null,
    project_id: String(values.get("project_id") || "") || null, due_kind: kind,
    due_date: kind === "date" ? dueDate : null, due_at: kind === "datetime" ? dueAt : null,
    due_timezone: kind === "datetime" ? zone : null };
}
