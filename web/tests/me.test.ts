import { beforeEach, describe, expect, it, vi } from "vitest";
import { getMe } from "../src/server/api/me";
import { getServerUser } from "../src/server/auth/session";
import { readProfile } from "../src/server/api/profile";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerUser: vi.fn() }));
vi.mock("../src/server/api/profile", () => ({ readProfile: vi.fn() }));

describe("getMe", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rejects an anonymous caller before reading a profile", async () => {
    vi.mocked(getServerUser).mockResolvedValue(null);
    await expect(getMe()).resolves.toEqual({ kind: "unauthorized" });
    expect(readProfile).not.toHaveBeenCalled();
  });

  it("projects only nonsecret fields for the verified owner", async () => {
    vi.mocked(getServerUser).mockResolvedValue({
      id: "user-123",
      email: "owner@example.com",
    });
    vi.mocked(readProfile).mockResolvedValue({
      kind: "ok",
      profile: {
        id: "user-123",
        timezone: "Asia/Jakarta",
        working_hours: { days: [1, 2, 3], start_minute: 540, end_minute: 1020 },
        is_allowlisted: true,
        access_token: "do-not-return",
      } as never,
    });

    const result = await getMe();
    expect(result).toEqual({
      kind: "ok",
      data: {
        user: { id: "user-123", email: "owner@example.com" },
        profile: {
          timezone: "Asia/Jakarta",
          working_hours: { days: [1, 2, 3], start_minute: 540, end_minute: 1020 },
        },
      },
    });
    expect(JSON.stringify(result)).not.toContain("access_token");
    expect(JSON.stringify(result)).not.toContain("is_allowlisted");
  });

  it("rejects a profile whose owner does not match the verified user", async () => {
    vi.mocked(getServerUser).mockResolvedValue({ id: "user-123", email: null });
    vi.mocked(readProfile).mockResolvedValue({
      kind: "ok",
      profile: {
        id: "other-user",
        timezone: "UTC",
        working_hours: { days: [1], start_minute: 0, end_minute: 60 },
      },
    });

    await expect(getMe()).resolves.toEqual({
      kind: "unavailable",
      user: { id: "user-123", email: null },
    });
  });
});
