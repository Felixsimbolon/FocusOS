import { beforeEach, describe, expect, it, vi } from "vitest";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/integrations/google/gmail/sync/route";
import { POST as processOne } from "../src/app/api/integrations/google/gmail/process-one/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

describe("Gmail sync controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-user-token");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("denies anonymous status and actions before calling API", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await GET()).status).toBe(401);
    expect((await POST()).status).toBe(401);
    expect((await processOne()).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards token server-side and returns safe sync state", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ state: "partial", imported: 2 }));
    const response = await POST();
    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data).toEqual({ state: "partial", imported: 2 });
    expect(fetch).toHaveBeenCalledWith("https://api.example.test/connections/google/gmail/sync",
      expect.objectContaining({ method: "POST", headers: { Authorization: "Bearer private-user-token" } }));
    expect(JSON.stringify(data)).not.toContain("private-user-token");
  });

  it("hides upstream details while preserving a reconnect status", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "private provider secret" }, { status: 409 }));
    const response = await POST();
    expect(response.status).toBe(409);
    expect(await response.text()).not.toContain("private provider secret");
  });

  it("loads scoped status and one extraction", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ connection_status: "connected", source_count: 0 }))
      .mockResolvedValueOnce(Response.json({ state: "no_pending" }));
    expect((await GET()).status).toBe(200);
    expect((await processOne()).status).toBe(200);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("https://api.example.test/connections/google/gmail/sync/status");
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe("https://api.example.test/connections/google/gmail/process-one");
  });
});

