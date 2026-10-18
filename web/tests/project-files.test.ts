import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { agenda, fileSize, tabFromHash, type ProjectDetail } from "../src/app/projects/project-view";
import { peaks, progress, rangePath, MAX_PEAKS } from "../src/app/projects/range";
import { rangeStatus } from "../src/app/projects/projects-index";
import { projectLine, type ProjectSummary } from "../src/app/projects/projects-panel";
import { POST as FILE_POST } from "../src/app/api/projects/[projectId]/files/route";
import { DELETE as FILE_DELETE, GET as FILE_GET } from "../src/app/api/files/[fileId]/route";
import { getServerAccessToken } from "../src/server/auth/session";
vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));

const id = "123e4567-e89b-42d3-a456-426614174000";
const fileId = "223e4567-e89b-42d3-a456-426614174000";
const summary = (changes: Partial<ProjectSummary> = {}): ProjectSummary => ({ id, name: "Statistika", open_tasks: 3, done_tasks: 1, notes: 0, assignments: 0,
  next_deadline: null, next_block: null, ...changes });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ id: fileId }, { status: 201 })));
});

describe("project schedule", () => {
  const task = (id: string, due: string | null, status = "open") => ({ id, title: `[Statistika] ${id}`, status, priority: "normal", due_kind: due ? "date" : "none",
    due_date: due, due_at: null, estimate_minutes: null, version: 1 });
  it("groups blocks and deadlines by local day, soonest first, blocks before deadlines", () => {
    const days = agenda({ name: "Statistika", tasks: [task("laporan", "2026-10-20"), task("lama", "2026-10-01"), task("selesai", "2026-10-20", "done"), task("kapan saja", null)],
      upcoming: [{ id: "b", title: "[Statistika] Belajar", start: "2026-10-19T17:30:00Z", end: "2026-10-19T19:00:00Z", timezone: "Asia/Jakarta" }] }, "2026-10-18");
    expect(days.map(day => day.date)).toEqual(["2026-10-20"]);
    expect(days[0].items.map(item => [item.kind, item.title, item.time])).toEqual([["block", "Belajar", "00:30–02:00"], ["deadline", "laporan", null]]);
  });
  it("reads the open tab from the address", () => {
    expect(tabFromHash("#files")).toBe("files");
    expect(tabFromHash("#nope")).toBe("overview");
    expect(tabFromHash("")).toBe("overview");
  });
  it("writes sizes people read", () => {
    expect(fileSize(320_000)).toBe("320 KB");
    expect(fileSize(1_240_000)).toBe("1.2 MB");
    expect(fileSize(10)).toBe("1 KB");
  });
});

describe("projects range", () => {
  it("lights the route by the share of tasks done", () => {
    expect(progress(summary())).toBe(0.25);
    expect(progress(summary({ open_tasks: 0, done_tasks: 0 }))).toBe(0);
  });
  it("draws at most a few peaks, spread across the width, above the valley", () => {
    const many = Array.from({ length: 10 }, (_, index) => summary({ id: `p${index}`, open_tasks: index }));
    const points = peaks(many);
    expect(points).toHaveLength(MAX_PEAKS);
    expect(points.every((point, index) => !index || point.x > points[index - 1].x)).toBe(true);
    expect(points.every(point => point.y > 0 && point.y < 372)).toBe(true);
    expect(rangePath(points)).toMatch(/^M0 .* Z$/);
    expect(rangePath([])).toContain("Z");
    expect(rangeStatus(many)).toContain(`first ${MAX_PEAKS}`);
    expect(rangeStatus([])).toContain("No projects yet");
  });
  it("mentions files in a project's line", () => {
    expect(projectLine(summary({ files: 2 }))).toBe("3 open tasks, 2 files");
  });
});

describe("file routes", () => {
  const upload = (file: File, extra: Record<string, string> = {}) => {
    const form = new FormData(); form.append("id", fileId); form.append("file", file);
    for (const [key, value] of Object.entries(extra)) form.append(key, value);
    return FILE_POST(new NextRequest(`http://localhost/api/projects/${id}/files`, { method: "POST", body: form }), { params: Promise.resolve({ projectId: id }) });
  };
  it("forwards one checked file as base64", async () => {
    const response = await upload(new File(["%PDF-1.7"], "brief.pdf", { type: "application/pdf" }));
    expect(response.status).toBe(201);
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`https://api.example.test/projects/${id}/files`);
    expect(JSON.parse(String(init.body))).toEqual({ id: fileId, filename: "brief.pdf", mime_type: "application/pdf", data: Buffer.from("%PDF-1.7").toString("base64") });
  });
  it("refuses other types, extra fields and missing sessions without calling the API", async () => {
    expect((await upload(new File(["x"], "a.exe", { type: "application/x-msdownload" }))).status).toBe(415);
    expect((await upload(new File(["%PDF"], "a.pdf", { type: "application/pdf" }), { project_id: id })).status).toBe(400);
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await upload(new File(["%PDF"], "a.pdf", { type: "application/pdf" }))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("opens and deletes by id only", async () => {
    vi.mocked(fetch).mockImplementation(async () => Response.json({ url: "https://db.example/storage/v1/object/sign/x" }));
    const link = await FILE_GET(new Request("http://localhost"), { params: Promise.resolve({ fileId }) });
    expect(await link.json()).toEqual({ url: "https://db.example/storage/v1/object/sign/x" });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(`https://api.example.test/files/${fileId}/link`);
    await FILE_DELETE(new Request("http://localhost", { method: "DELETE" }), { params: Promise.resolve({ fileId }) });
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(`https://api.example.test/files/${fileId}/delete`);
    expect((await FILE_GET(new Request("http://localhost"), { params: Promise.resolve({ fileId: "../x" }) })).status).toBe(404);
  });
  it("passes the API's short reason when a file is refused", async () => {
    vi.mocked(fetch).mockImplementation(async () => Response.json({ detail: "This file does not look like a PDF, PNG, JPEG or WebP image." }, { status: 422 }));
    const response = await upload(new File(["MZ"], "a.pdf", { type: "application/pdf" }));
    expect(response.status).toBe(422);
    expect((await response.json()).error).toContain("does not look like");
  });
});
