import { beforeEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../src/lib/supabase/server";
import { getServerUser } from "../src/server/auth/session";

vi.mock("../src/lib/supabase/server", () => ({
  createClient: vi.fn(),
}));

const mockGetUser = vi.fn();

describe("getServerUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createClient).mockResolvedValue({
      auth: { getUser: mockGetUser },
    } as never);
  });

  it("returns only identity fields from a verified user", async () => {
    mockGetUser.mockResolvedValue({
      data: {
        user: {
          id: "user-123",
          email: "owner@example.com",
          app_metadata: { provider: "google" },
          user_metadata: { full_name: "Owner" },
        },
      },
      error: null,
    });

    await expect(getServerUser()).resolves.toEqual({
      id: "user-123",
      email: "owner@example.com",
    });
  });

  it("rejects an absent or invalid session", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: null },
      error: new Error("Invalid session"),
    });

    await expect(getServerUser()).resolves.toBeNull();
  });

  it("fails closed when session verification throws", async () => {
    mockGetUser.mockRejectedValue(new Error("Auth service unavailable"));

    await expect(getServerUser()).resolves.toBeNull();
  });
});
