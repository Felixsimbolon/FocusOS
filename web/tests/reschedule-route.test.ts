import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, after } from "next/server";
import { POST } from "../src/app/api/focus-blocks/[id]/reschedule/route";
import { GET, POST as PRODUCT_POST } from "../src/app/api/product/[[...path]]/route";
import { getServerAccessToken } from "../src/server/auth/session";
vi.mock("server-only", () => ({}));
vi.mock("next/server", async original => ({ ...(await original<typeof import("next/server")>()), after: vi.fn() }));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));
vi.mock("../src/server/jobs", () => ({ runBackgroundJob: vi.fn() }));
const id = "123e4567-e89b-42d3-a456-426614174000";
const key = "223e4567-e89b-42d3-a456-426614174000";
const move = (body: unknown, block = id) => POST(new NextRequest("http://localhost", { method: "POST", body: JSON.stringify(body) }), { params: Promise.resolve({ id: block }) });
const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) });
describe("moving a conflicting block", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ run_id: id, background_job: { id } })));
  });
  it("forwards only the replay key and runs the job after responding", async () => {
    expect((await move({ request_key: key })).status).toBe(202);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(`https://api.example.test/commands/reschedule/${id}`);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({ request_key: key });
    expect(after).toHaveBeenCalled();
  });
  it("rejects bad input and passes the API's fixed refusal through", async () => {
    expect((await move({ request_key: key, title: "x" })).status).toBe(400);
    expect((await move({ request_key: key }, "not-a-block")).status).toBe(404);
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "Only an upcoming FocusOS block can be moved." }, { status: 409 }));
    const refused = await move({ request_key: key });
    expect((await refused.json()).error).toBe("Only an upcoming FocusOS block can be moved.");
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await move({ request_key: key })).status).toBe(401);
  });
});
describe("new product routes", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ ok: true })));
  });
  it("allows the new read routes and nothing else", async () => {
    for (const path of [["conflicts"], ["triage"], ["graph"], ["review", "current"], ["review", "previous"]])
      expect((await GET(new NextRequest("http://localhost"), ctx(path))).status).toBe(200);
    expect((await GET(new NextRequest("http://localhost"), ctx(["review", "2020"]))).status).toBe(404);
  });
  it("validates triage corrections and allows review and graph actions", async () => {
    const post = (path: string[], body?: unknown) => PRODUCT_POST(new NextRequest("http://localhost", { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }), ctx(path));
    expect((await post(["triage", id], { priority: "urgent" })).status).toBe(200);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({ priority: "urgent" });
    expect((await post(["triage", id], { priority: "delete" })).status).toBe(400);
    expect((await post(["triage", "x"], { priority: "fyi" })).status).toBe(404);
    expect((await post(["graph", "backfill"])).status).toBe(200);
    expect((await post(["review", "previous"])).status).toBe(200);
  });
});
