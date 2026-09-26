import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET as getToday } from "../src/app/api/tasks/today/route";
import { PATCH } from "../src/app/api/tasks/[taskId]/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));

const taskId = "4304c278-a7e8-42d7-a6b3-825986f71112";

describe("Today and task update routes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("private-user-token");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("proxies the user-scoped Today list without exposing the token", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ tasks: [], today: "2026-03-08", timezone: "Asia/Jakarta", truncated: false }),
    );
    const response = await getToday();
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.example.test/tasks/today"),
      expect.objectContaining({
        headers: { Authorization: "Bearer private-user-token" },
        cache: "no-store",
        redirect: "error",
      }),
    );
    expect(await response.text()).not.toContain("private-user-token");
  });

  it("rejects anonymous patch requests before contacting FastAPI", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    const response = await PATCH(
      new NextRequest("http://localhost/api/tasks/" + taskId, {
        method: "PATCH",
        body: JSON.stringify({ expected_version: 1, status: "done" }),
      }),
      { params: Promise.resolve({ taskId }) },
    );
    expect(response.status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forwards a versioned update over the server-only session", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ outcome: "updated", task: { id: taskId, status: "done", version: 2 } }),
    );
    const response = await PATCH(
      new NextRequest("http://localhost/api/tasks/" + taskId, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: 1, status: "done" }),
      }),
      { params: Promise.resolve({ taskId }) },
    );
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.example.test/tasks/" + taskId),
      expect.objectContaining({
        method: "PATCH",
        headers: {
          Authorization: "Bearer private-user-token",
          "Content-Type": "application/json",
        },
        redirect: "error",
      }),
    );
  });

  it("maps a stale version conflict to a safe reload message", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ detail: { task: { title: "private row" } } }, { status: 409 }),
    );
    const response = await PATCH(
      new NextRequest("http://localhost/api/tasks/" + taskId, {
        method: "PATCH",
        body: JSON.stringify({ expected_version: 1, status: "done" }),
      }),
      { params: Promise.resolve({ taskId }) },
    );
    expect(response.status).toBe(409);
    expect(await response.text()).not.toContain("private row");
  });

  it("rejects malformed task IDs without proxying", async () => {
    const response = await PATCH(
      new NextRequest("http://localhost/api/tasks/not-a-uuid", {
        method: "PATCH",
        body: JSON.stringify({ expected_version: 1, status: "done" }),
      }),
      { params: Promise.resolve({ taskId: "not-a-uuid" }) },
    );
    expect(response.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });
});
