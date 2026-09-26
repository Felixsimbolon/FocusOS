import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/sources/[[...path]]/route";
import { POST as reviewPost } from "../src/app/api/extractions/[...path]/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

const sourceContext = (path?: string[]) => ({ params: Promise.resolve({ path }) });
const reviewContext = (path: string[]) => ({ params: Promise.resolve({ path }) });
const sourceId = "4304c278-a7e8-42d7-a6b3-825986f71112";

describe("extraction review proxy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-user-token");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("denies anonymous source and confirmation requests", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await GET(new NextRequest("http://localhost/api/sources"), sourceContext())).status).toBe(401);
    expect((await reviewPost(new NextRequest("http://localhost/api/extractions/" + sourceId + "/confirm",
      { method: "POST", body: "{}" }), reviewContext([sourceId, "confirm"]))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards only an allowed source path and keeps token server-side", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ sources: [] }));
    const response = await GET(new NextRequest("http://localhost/api/sources"), sourceContext());
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(new URL("https://api.example.test/sources"),
      expect.objectContaining({ headers: { Authorization: "Bearer private-user-token" } }));
    expect(await response.text()).not.toContain("private-user-token");
    expect((await GET(new NextRequest("http://localhost/api/sources/unknown"), sourceContext(["unknown"]))).status).toBe(404);
  });

  it("requires a replay key for manual input", async () => {
    const request = new NextRequest("http://localhost/api/sources/manual", {
      method: "POST", body: JSON.stringify({ title: "Fixture", text: "Finish slides" }),
    });
    expect((await POST(request, sourceContext(["manual"]))).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("proxies reviewed confirmation and hides backend error details", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "secret internal data" }, { status: 409 }));
    const response = await reviewPost(new NextRequest("http://localhost/api/extractions/" + sourceId + "/confirm", {
      method: "POST", body: JSON.stringify({ local_ref: "task-1", task: { title: "Submit slides" } }),
    }), reviewContext([sourceId, "confirm"]));
    expect(response.status).toBe(409);
    expect(await response.text()).not.toContain("secret internal data");
  });
});
