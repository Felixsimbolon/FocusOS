import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { daysLeft, dueOf, ProjectView, trailPoint, trailT, type ProjectDetail } from "../src/app/projects/project-view";
import { NotesPanel } from "../src/app/notes/notes-panel";
import { loadHome } from "../src/server/api/home";
import { getServerAccessToken } from "../src/server/auth/session";
vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));

const id = "123e4567-e89b-42d3-a456-426614174000";
const task = (changes: Partial<ProjectDetail["tasks"][number]> = {}) => ({ id: "t", title: "[Statistika] Tulis laporan", status: "open", priority: "normal",
  due_kind: "date", due_date: "2026-10-24", due_at: null, estimate_minutes: 60, version: 1, ...changes }) as ProjectDetail["tasks"][number];
const detail: ProjectDetail = { id, name: "Statistika", deadline: "2026-10-24", tasks: [task()], notes: [], assignments: [], upcoming: [] } as unknown as ProjectDetail;
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("React", React); });

describe("project trail", () => {
  it("runs from today on the left to the summit on the right, rising", () => {
    const [x0, y0] = trailPoint(0), [x1, y1] = trailPoint(1);
    expect(x0).toBeLessThan(x1);
    expect(y1).toBeLessThan(y0);
    expect(trailPoint(2)).toEqual(trailPoint(1));
  });
  it("places dates between today and the last deadline", () => {
    expect(trailT("2026-10-18", "2026-10-18", "2026-10-28")).toBe(0);
    expect(trailT("2026-10-23", "2026-10-18", "2026-10-28")).toBeCloseTo(0.5);
    expect(trailT("2026-11-30", "2026-10-18", "2026-10-28")).toBe(1);
    expect(trailT("2026-10-25", "2026-10-18", null)).toBeCloseTo(0.5);
    expect(trailT("2026-10-18", "2026-10-20", "2026-10-19")).toBe(1);
  });
  it("counts days to the summit and reads both due kinds", () => {
    expect(daysLeft("2026-10-18", "2026-10-24")).toBe(6);
    expect(daysLeft("2026-10-18", null)).toBeNull();
    expect(dueOf(task())).toBe("2026-10-24");
    expect(dueOf(task({ due_kind: "datetime", due_date: null, due_at: "2026-10-22T16:59:00Z" }))).toBe("2026-10-22");
    expect(dueOf(task({ due_kind: "none", due_date: null }))).toBeNull();
  });
  it("renders the project page with its notes, ask box and tasks", () => {
    const html = renderToStaticMarkup(React.createElement(ProjectView, { id, initial: detail, timezone: "Asia/Jakarta" }));
    expect(html).toContain("<h1");
    expect(html).toContain("Statistika");
    expect(html).toContain("Tulis laporan");
    expect(html).toContain("No notes for this project yet");
  });
});

describe("project notes", () => {
  it("hides the project choice on a project page, where every note belongs to it", () => {
    const scoped = renderToStaticMarkup(React.createElement(NotesPanel, { projectId: id }));
    const home = renderToStaticMarkup(React.createElement(NotesPanel));
    expect(scoped).not.toContain("note-project");
    expect(home).toContain("note-project");
  });
});

describe("loadHome", () => {
  it("reads nothing without a session", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    await expect(loadHome()).resolves.toEqual({ today: null, open: null, projects: null, blocks: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("keeps what loaded and leaves a failed read to the browser", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => url.endsWith("/projects") ? Response.json({ projects: [{ id, name: "Statistika", created_at: "x" }] })
      : url.endsWith("/product/focus-blocks") ? Response.json({ error: "down" }, { status: 503 }) : Response.json({ tasks: [], truncated: false })));
    const home = await loadHome();
    expect(home.projects).toHaveLength(1);
    expect(home.today).toEqual({ tasks: [], truncated: false });
    expect(home.blocks).toBeNull();
  });
});
