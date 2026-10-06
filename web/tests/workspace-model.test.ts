import { describe, expect, it } from "vitest";
import { filterTasks, taskEditPayload } from "../src/app/tasks/workspace-model";
import type { Task } from "../src/app/tasks/task-board";
const task = { id: "a", title: "Brief", description: "Aurora", priority: "normal", project_id: "p", version: 2, due_kind: "none", due_date: null, due_at: null } as Task;
describe("task workspace", () => {
  it("filters title, description, project, priority and sorts urgency then deadline", () => {
    const items = [task, { ...task, id: "b", priority: "high", due_date: "2026-10-12" } as Task, { ...task, id: "c", priority: "high", due_date: "2026-10-10" } as Task];
    expect(filterTasks(items, "aurora", "p", "").map(t => t.id)).toEqual(["c", "b", "a"]);
    expect(filterTasks(items, "", "other", "")).toEqual([]);
  });
  it("clears every deadline field together and preserves version", () => {
    const f = new FormData(); f.set("title", " Brief "); f.set("due_kind", "none"); f.set("priority", "high");
    expect(taskEditPayload(task, f)).toMatchObject({ expected_version: 2, title: "Brief", due_kind: "none", due_date: null, due_at: null, due_timezone: null, estimate_minutes: null });
  });
  it("rejects ambiguous timestamps and invalid estimates", () => {
    const f = new FormData(); f.set("title", "Brief"); f.set("due_kind", "datetime"); f.set("due_at", "2026-10-12T17:00");
    expect(() => taskEditPayload(task, f)).toThrow("offset"); f.set("estimate", "2.5"); expect(() => taskEditPayload(task, f)).toThrow("Estimate");
  });
});
