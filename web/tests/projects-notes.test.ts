import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, after } from "next/server";
import { Steps, hours, previewTasks, stageOf, type Analysis, type Assignment } from "../src/app/projects/assignment-flow";
import { projectLine, type ProjectSummary } from "../src/app/projects/projects-panel";
import { filterNotes, saveLabel, startingProject, type NoteSummary } from "../src/app/notes/notes-panel";
import { POST as ASSIGNMENT_POST } from "../src/app/api/assignments/[[...path]]/route";
import { GET as NOTES_GET, POST as NOTES_POST } from "../src/app/api/notes/[[...path]]/route";
import { GET as PROJECT_GET } from "../src/app/api/projects/[projectId]/route";
import { getServerAccessToken } from "../src/server/auth/session";
vi.mock("server-only", () => ({}));
vi.mock("next/server", async original => ({ ...(await original<typeof import("next/server")>()), after: vi.fn() }));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));
vi.mock("../src/server/jobs", () => ({ runBackgroundJob: vi.fn() }));

const id = "123e4567-e89b-42d3-a456-426614174000";
const key = "223e4567-e89b-42d3-a456-426614174000";
const analysis: Analysis = { title: "Tugas 2", summary: "Regresi.", project_name: "Statistika", deliverables: [],
  due: { raw_text: "24 Oktober", date: "2026-10-24", time: null },
  concepts: [{ name: "Regresi linear", why: "Inti.", study_minutes: 105 }, { name: "Uji asumsi", why: "Sah.", study_minutes: 60 }],
  subtasks: [{ title: "Tulis laporan", estimate_minutes: 120 }] };
const assignment = (changes: Partial<Assignment> = {}): Assignment => ({ id, title: "Tugas 2", status: "questions", analysis, understanding: {}, project_id: null, version: 2, ...changes });
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal("React", React);
  vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ background_job: { id: "job" }, created: 3 })));
});

describe("assignment flow", () => {
  it("previews study sessions for what is not understood, then the subtasks, all tagged", () => {
    const tasks = previewTasks(analysis, { "0": "partly", "1": "understood" }, "Statistika");
    expect(tasks).toEqual([{ title: "[Statistika] Belajar: Regresi linear", minutes: 60, kind: "study" }, { title: "[Statistika] Tulis laporan", minutes: 120, kind: "work" }]);
  });
  it("resumes at the right step", () => {
    expect(stageOf(null)).toBe("pick");
    expect(stageOf(assignment({ analysis: null, status: "transcribed" }))).toBe("analyzing");
    expect(stageOf(assignment())).toBe("questions");
    expect(stageOf(assignment({ understanding: { "0": "not", "1": "understood" } }))).toBe("plan");
    expect(stageOf(assignment({ status: "planned" }))).toBe("done");
    expect(hours(105)).toBe("1 j 45 m");
    const html = renderToStaticMarkup(React.createElement(Steps, { stage: "questions" }));
    expect(html).toContain('aria-current="step"');
    expect(html).toContain("Pahami konsep");
  });
  it("routes each step and runs the booking job after planning", async () => {
    const post = (path: string[], body?: unknown) => ASSIGNMENT_POST(new NextRequest("http://localhost", { method: "POST", body: body ? JSON.stringify(body) : undefined }), { params: Promise.resolve({ path }) });
    expect((await post([id, "analyze"])).status).toBe(200);
    expect((await post([id, "understanding"], { expected_version: 2, answers: { "0": "not" } })).status).toBe(200);
    expect((await post([id, "understanding"], { expected_version: 2, answers: { "0": "maybe" } })).status).toBe(400);
    expect((await post([id, "plan"], { expected_version: 2, request_key: key, project_name: "Statistika" })).status).toBe(202);
    expect(after).toHaveBeenCalled();
    expect((await post([id, "delete"])).status).toBe(404);
  });
  it("uploads one supported file as base64", async () => {
    const form = new FormData(); form.set("file", new File(["%PDF-1.7"], "tugas2.pdf", { type: "application/pdf" })); form.set("request_key", key);
    expect((await ASSIGNMENT_POST(new NextRequest("http://localhost", { method: "POST", body: form }), { params: Promise.resolve({}) })).status).toBe(200);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toMatchObject({ filename: "tugas2.pdf", mime_type: "application/pdf" });
  });
});

describe("projects and notes", () => {
  it("summarizes a project in one line", () => {
    const project: ProjectSummary = { id, name: "Statistika", open_tasks: 3, done_tasks: 1, notes: 2, assignments: 1, next_deadline: "2026-10-24", next_block: null };
    expect(projectLine(project)).toBe("3 open tasks, next deadline 2026-10-24, 2 notes, 1 assignment");
  });
  it("filters notes by words and project", () => {
    const notes: NoteSummary[] = [{ id: "a", project_id: id, title: "Kuliah 3", excerpt: "Regresi linear", version: 1, updated_at: "2026-10-18T00:00:00Z" },
      { id: "b", project_id: null, title: "Ide startup", excerpt: "Aplikasi catatan", version: 1, updated_at: "2026-10-18T00:00:00Z" }];
    expect(filterNotes(notes, "regresi", "all").map(n => n.id)).toEqual(["a"]);
    expect(filterNotes(notes, "", "none").map(n => n.id)).toEqual(["b"]);
    expect(filterNotes(notes, "", id).map(n => n.id)).toEqual(["a"]);
    expect(saveLabel(true, false)).toBe("Save note");
    expect(saveLabel(false, false)).toBe("Saved");
  });
  it("starts a new note in the page's, the filtered or the only project", () => {
    const other = "22222222-2222-4222-8222-222222222222";
    expect(startingProject(id, "all", [])).toBe(id);
    expect(startingProject(undefined, other, [{ id }, { id: other }])).toBe(other);
    expect(startingProject(undefined, "all", [{ id }])).toBe(id);
    expect(startingProject(undefined, "all", [{ id }, { id: other }])).toBeNull();
    expect(startingProject(undefined, "none", [])).toBeNull();
  });
  it("validates note saves and proxies reads", async () => {
    const save = (body: unknown) => NOTES_POST(new NextRequest("http://localhost", { method: "POST", body: JSON.stringify(body) }), { params: Promise.resolve({ path: [id] }) });
    expect((await save({ title: "Kuliah 3", body: "isi", expected_version: 0, project_id: id })).status).toBe(200);
    // Every note belongs to a project.
    for (const project_id of [null, undefined, "not-a-uuid"]) {
      const refused = await save({ title: "Kuliah 3", body: "isi", expected_version: 0, project_id });
      expect(refused.status).toBe(400);
      expect((await refused.json()).error).toBe("Choose a project for this note.");
    }
    expect((await save({ title: "", body: "isi", expected_version: 0 })).status).toBe(400);
    expect((await save({ title: "x", body: "isi", expected_version: 0, owner: "someone" })).status).toBe(400);
    expect((await NOTES_GET(new NextRequest(`http://localhost/api/notes?project_id=${id}`), { params: Promise.resolve({}) })).status).toBe(200);
    expect(vi.mocked(fetch).mock.calls.at(-1)![0]).toBe(`https://api.example.test/notes?project_id=${id}`);
    expect((await PROJECT_GET(new Request("http://localhost"), { params: Promise.resolve({ projectId: "overview" }) })).status).toBe(200);
    expect((await PROJECT_GET(new Request("http://localhost"), { params: Promise.resolve({ projectId: "../admin" }) })).status).toBe(404);
  });
});
