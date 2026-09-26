import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/tasks/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

describe("task API route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-user-token");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("rejects anonymous callers before contacting FastAPI", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    const response = await GET(new NextRequest("http://localhost/api/tasks"));
    expect(response.status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("passes only allowed list filters and keeps the session token server-side", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ tasks: [], truncated: false }),
    );
    const response = await GET(
      new NextRequest("http://localhost/api/tasks?status=open&limit=25&other=ignore"),
    );
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.example.test/tasks?status=open&limit=25"),
      expect.objectContaining({
        headers: { Authorization: "Bearer private-user-token" },
        cache: "no-store",
      }),
    );
    expect(await response.text()).not.toContain("private-user-token");
  });

  it("rejects invalid filters without calling FastAPI", async () => {
    const response = await GET(
      new NextRequest("http://localhost/api/tasks?status=unknown"),
    );
    expect(response.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("requires a valid idempotency key before forwarding task data", async () => {
    const response = await POST(
      new NextRequest("http://localhost/api/tasks", {
        method: "POST",
        body: JSON.stringify({ title: "Task" }),
      }),
    );
    expect(response.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards a validated session and key but never returns the access token", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ task: { id: "task-1" }, replayed: false }),
    );
    const response = await POST(
      new NextRequest("http://localhost/api/tasks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "4304c278-a7e8-42d7-a6b3-825986f71112",
        },
        body: JSON.stringify({ title: "Task" }),
      }),
    );
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.example.test/tasks"),
      expect.objectContaining({
        method: "POST",
        headers: {
          Authorization: "Bearer private-user-token",
          "Content-Type": "application/json",
          "Idempotency-Key": "4304c278-a7e8-42d7-a6b3-825986f71112",
        },
      }),
    );
    expect(await response.text()).not.toContain("private-user-token");
  });

  it("preserves an idempotency conflict as HTTP 409", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ detail: "internal request data" }, { status: 409 }),
    );
    const response = await POST(
      new NextRequest("http://localhost/api/tasks", {
        method: "POST",
        headers: {
          "Idempotency-Key": "4304c278-a7e8-42d7-a6b3-825986f71112",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: "Task" }),
      }),
    );
    expect(response.status).toBe(409);
    expect(await response.text()).not.toContain("internal request data");
  });
});
