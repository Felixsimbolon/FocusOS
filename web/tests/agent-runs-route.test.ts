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
  it("forwards a bounded start command and continuation", async () => {
    expect((await POST(new NextRequest("http://localhost/api/agent/runs", { method:"POST",body:"{}" }), context())).status).toBe(200);
    expect((await POST(new NextRequest(`http://localhost/api/agent/runs/${id}/continue`, { method:"POST" }), context([id,"continue"]))).status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

