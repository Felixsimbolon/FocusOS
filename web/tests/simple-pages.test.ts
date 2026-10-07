import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "../src/app/page";
import { SourceReview } from "../src/app/activity/source-review";
import { getMe } from "../src/server/api/me";
import { redirect } from "next/navigation";
import Tasks from "../src/app/tasks/page";
import Schedule from "../src/app/schedule/page";
import System from "../src/app/system/page";
import Memories from "../src/app/memories/page";
vi.mock("server-only", () => ({}));
vi.mock("../src/server/api/me", () => ({ getMe: vi.fn() }));
vi.mock("../src/app/auth/actions", () => ({ signInWithGoogle: vi.fn(), signOut: vi.fn() }));
vi.mock("../src/app/settings/actions", () => ({ saveSettings: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn((path: string) => { throw new Error(path); }) }));
beforeEach(() => { vi.stubGlobal("React", React); vi.clearAllMocks(); });
describe("simplified navigation and input", () => {
  it("puts search and preferences on Home without task/project creation or dashboard links", async () => {
    vi.mocked(getMe).mockResolvedValue({ kind: "ok", data: { user: { id: "synthetic-owner", email: null }, profile: { timezone: "Asia/Jakarta", working_hours: { days: [1,2,3,4,5], start_minute: 540, end_minute: 1020 } } } });
    const html = renderToStaticMarkup(await Home({ searchParams: Promise.resolve({}) }));
    expect(html).toContain('id="memories"');
    expect(html).toContain('id="preferences"');
    expect(html).toContain('id="schedule"');
    for (const name of ["Add a task", "New project", "Task workspace", "Jobs, diagnostics"]) expect(html).not.toContain(name);
    for (const path of ["/tasks", "/schedule", "/system", "/memories", "/settings"]) expect(html).not.toContain(`href="${path}"`);
  });
  it("offers one plain text input without individual task fields", () => {
    const html = renderToStaticMarkup(React.createElement(SourceReview));
    expect(html).toContain("Work description");
    expect(html.match(/<textarea/g)).toHaveLength(1);
    expect(html).toContain("Organize my work");
    expect(html).not.toContain("<input");
    expect(html).not.toContain("Job status");
  });
  it("old page URLs lead to the matching Home section", () => {
    for (const [page, path] of [[Tasks, "/#tasks-heading"], [Schedule, "/#schedule"], [System, "/"], [Memories, "/#memories"]] as const) {
      expect(() => page()).toThrow(path);
      expect(redirect).toHaveBeenLastCalledWith(path);
    }
  });
});
