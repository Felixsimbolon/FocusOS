import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/projects/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

describe("project API route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-user-token");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("rejects anonymous reads and writes", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    const getResponse = await GET();
    const postResponse = await POST(
      new NextRequest("http://localhost/api/projects", {
        method: "POST",
        body: JSON.stringify({ name: "Portfolio" }),
      }),
    );
    expect(getResponse.status).toBe(401);
    expect(postResponse.status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards project reads with a server-only session token", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ projects: [] }));
    const response = await GET();
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.example.test/projects"),
      expect.objectContaining({
        headers: { Authorization: "Bearer private-user-token" },
        redirect: "error",
        cache: "no-store",
      }),
    );
    expect(await response.text()).not.toContain("private-user-token");
  });

  it("forwards project creation and returns only the safe API response", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        project: { id: "project-1", name: "Portfolio", created_at: "2026-09-26T12:00:00Z" },
        existing: false,
      }),
    );
    const response = await POST(
      new NextRequest("http://localhost/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Portfolio" }),
      }),
    );
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.example.test/projects"),
      expect.objectContaining({
        method: "POST",
        headers: {
          Authorization: "Bearer private-user-token",
          "Content-Type": "application/json",
        },
      }),
    );
  });
});
