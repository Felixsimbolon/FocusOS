import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET } from "../src/app/api/integrations/google/calendar/availability/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

describe("Calendar availability proxy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-session");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("denies anonymous requests without provider calls", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await GET(new NextRequest("http://localhost/api/integrations/google/calendar/availability"))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects invalid window and duration before provider calls", async () => {
    const request = new NextRequest("http://localhost/api/integrations/google/calendar/availability?days=15&duration_minutes=0");
    expect((await GET(request)).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards only allowed filters and hides token from result", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ complete: true, busy_events: [] }));
    const response = await GET(new NextRequest(
      "http://localhost/api/integrations/google/calendar/availability?days=7&duration_minutes=90&allow_split=true&ignored=secret"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.complete).toBe(true);
    expect(JSON.stringify(body)).not.toContain("private-session");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).not.toContain("ignored");
    expect(String(url)).toContain("duration_minutes=90");
    expect(init).toEqual(expect.objectContaining({
      headers: { Authorization: "Bearer private-session" }, cache: "no-store",
    }));
  });

  it("does not expose upstream provider errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "private Calendar body" }, { status: 422 }));
    const response = await GET(new NextRequest("http://localhost/api/integrations/google/calendar/availability"));
    expect(response.status).toBe(422);
    expect(await response.text()).not.toContain("private Calendar body");
  });
});
