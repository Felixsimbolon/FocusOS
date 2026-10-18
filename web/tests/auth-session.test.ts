import { beforeEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../src/lib/supabase/server";
import { getServerAccessToken, getServerUser } from "../src/server/auth/session";

vi.mock("../src/lib/supabase/server", () => ({
  createClient: vi.fn(),
}));

const mockGetUser = vi.fn();
const mockGetSession = vi.fn();

describe("getServerUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createClient).mockResolvedValue({
      auth: { getUser: mockGetUser, getSession: mockGetSession },
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

    // The first name is kept for the greeting; provider and raw metadata never leave.
    await expect(getServerUser()).resolves.toStrictEqual({
      id: "user-123",
      email: "owner@example.com",
      name: "Owner",
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

  it("retries once after a network hiccup, so a refresh does not look signed out", async () => {
    mockGetUser
      .mockResolvedValueOnce({ data: { user: null }, error: { name: "AuthRetryableFetchError", status: 0 } })
      .mockResolvedValueOnce({ data: { user: { id: "user-123", email: null, user_metadata: {} } }, error: null });

    await expect(getServerUser()).resolves.toStrictEqual({ id: "user-123", email: null });
    expect(mockGetUser).toHaveBeenCalledTimes(2);
  });

  it("does not retry a session Supabase rejected", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: { name: "AuthApiError", status: 401 } });

    await expect(getServerUser()).resolves.toBeNull();
    expect(mockGetUser).toHaveBeenCalledTimes(1);
  });
});

describe("getServerAccessToken", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createClient).mockResolvedValue({
      auth: { getUser: mockGetUser, getSession: mockGetSession },
    } as never);
    mockGetSession.mockResolvedValue({
      data: { session: { access_token: "verified-token", user: {} } },
      error: null,
    });
  });

  it("accepts a verified token when the cookie omits full user data", async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: "owner-123" } }, error: null });
    await expect(getServerAccessToken()).resolves.toBe("verified-token");
    expect(mockGetUser).toHaveBeenCalledWith("verified-token");
  });

  it("does not forward a token rejected by Supabase Auth", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: new Error("Invalid session") });
    await expect(getServerAccessToken()).resolves.toBeNull();
  });
});
