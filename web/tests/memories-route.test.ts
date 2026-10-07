import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/memories/[[...path]]/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

const context = (path?: string[]) => ({ params: Promise.resolve({ path }) });

describe("memory proxy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-session");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("blocks anonymous reads and writes", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await GET(new NextRequest("http://localhost/api/memories"), context())).status).toBe(401);
    expect((await POST(new NextRequest("http://localhost/api/memories", { method: "POST" }), context())).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards only allowlisted memory paths", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ memories: [] }));
    expect((await GET(new NextRequest("http://localhost/api/memories"), context())).status).toBe(200);
    expect((await GET(new NextRequest("http://localhost/api/memories/bad"), context(["bad"]))).status).toBe(404);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("hides upstream evidence errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "private source text" }, { status: 422 }));
    const response = await POST(new NextRequest("http://localhost/api/memories", {
      method: "POST", body: "{}",
    }), context());
    expect(response.status).toBe(422);
    expect(await response.text()).not.toContain("private source text");
  });
  it("forwards only a valid source filter, never an owner supplied by the browser", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ memories: [] }));
    const id = "123e4567-e89b-42d3-a456-426614174000";
    await GET(new NextRequest(`http://localhost/api/memories?source_id=${id}&user_id=other-owner`), context());
    expect(fetch).toHaveBeenCalledWith(`https://api.example.test/memories?source_id=${id}`, expect.anything());
    expect((await GET(new NextRequest("http://localhost/api/memories?source_id=invalid"), context())).status).toBe(422);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

});
