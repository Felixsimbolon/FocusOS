import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/agent/runs/[[...path]]/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));
const id = "123e4567-e89b-42d3-a456-426614174000";
const context = (path?: string[]) => ({ params: Promise.resolve({ path }) });

describe("agent run proxy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-session");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ id })));
  });
  it("requires a session for every route", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await GET(new NextRequest(`http://localhost/api/agent/runs/${id}`), context([id]))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("allows only owned-run-shaped paths and hides arbitrary upstream details", async () => {
    expect((await GET(new NextRequest(`http://localhost/api/agent/runs/${id}/tools`), context([id,"tools"]))).status).toBe(200);
    expect((await GET(new NextRequest(`http://localhost/api/agent/runs/${id}/audit`), context([id,"audit"]))).status).toBe(200);
    expect((await GET(new NextRequest("http://localhost/api/agent/runs/invalid"), context(["invalid"]))).status).toBe(404);
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "secret" }, { status: 404 }));
    const response = await GET(new NextRequest(`http://localhost/api/agent/runs/${id}`), context([id]));
    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("secret");
  });
  it("explains a known Calendar proposal reason without leaking unknown upstream details", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ detail: "calendar_write_required" }, { status: 409 }));
    const known = await POST(new NextRequest("http://localhost/api/agent/runs/" + id + "/propose-event",
      { method: "POST", body: JSON.stringify({ block_index: 0 }) }), context([id, "propose-event"]));
    expect(known.status).toBe(409);
    expect((await known.json()).error).toContain("Calendar write access");

    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ detail: "private SQL detail" }, { status: 409 }));
    const unknown = await POST(new NextRequest("http://localhost/api/agent/runs/" + id + "/propose-event",
      { method: "POST", body: JSON.stringify({ block_index: 0 }) }), context([id, "propose-event"]));
    expect(unknown.status).toBe(409);
    expect(await unknown.text()).not.toContain("private SQL detail");
  });
  it("only forwards bounded automatic Calendar block paths", async () => {
    expect((await POST(new NextRequest(`http://localhost/api/agent/runs/${id}/blocks/0/auto`, { method: "POST" }), context([id,"blocks","0","auto"]))).status).toBe(200);
    expect((await POST(new NextRequest(`http://localhost/api/agent/runs/${id}/blocks/16/auto`, { method: "POST" }), context([id,"blocks","16","auto"]))).status).toBe(404);
    expect(fetch).toHaveBeenCalledTimes(1);
  });  it("forwards a bounded start command and continuation", async () => {
    expect((await POST(new NextRequest("http://localhost/api/agent/runs", { method:"POST",body:"{}" }), context())).status).toBe(200);
    expect((await POST(new NextRequest(`http://localhost/api/agent/runs/${id}/continue`, { method:"POST" }), context([id,"continue"]))).status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

