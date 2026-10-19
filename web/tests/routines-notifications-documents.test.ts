import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, after } from "next/server";
import { RoutineList, nextLine, type Routine } from "../src/app/routines/routines-panel";
import { NotificationsForm, reason, sentLine, type Settings } from "../src/app/notifications/notifications-panel";
import { settingsBody } from "../src/app/notifications/settings-body";
import { documentMessage, workMessage } from "../src/app/work-composer";
import { POST as DOCUMENT } from "../src/app/api/documents/route";
import { DOCX, fileType } from "../src/lib/files";
import { POST as ROUTINE_POST } from "../src/app/api/routines/[[...path]]/route";
import { POST as NOTIFY_POST } from "../src/app/api/notifications/[[...path]]/route";
import manifest from "../src/app/manifest";
import { getServerAccessToken } from "../src/server/auth/session";
import type { Job } from "../src/app/jobs/client";
vi.mock("server-only", () => ({}));
vi.mock("next/server", async original => ({ ...(await original<typeof import("next/server")>()), after: vi.fn() }));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));
vi.mock("../src/server/jobs", () => ({ runBackgroundJob: vi.fn() }));

const key = "123e4567-e89b-42d3-a456-426614174000";
const job = (status: string, result: Record<string, unknown>): Job => ({ id: "j", kind: "source", subject_id: "s", status, result, safe_error: null,
  steps: 0, failures: 0, available_at: new Date().toISOString(), expires_at: new Date(Date.now() + 900000).toISOString() });
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal("React", React);
  vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ background_job: { id: "job" }, booking: 2 })));
});

describe("routines", () => {
  const routine: Routine = { id: "r", title: "Belajar Python", summary: "Belajar Python: Tue, Thu, 07:00–08:00", active: true, ends_on: null,
    upcoming: [{ date: "2026-10-20", status: "booked" }, { date: "2026-10-22", status: "failed" }] };
  it("says what was booked and why something was not", () => {
    expect(nextLine(routine)).toBe("1 booked this week, 1 could not fit (busy or outside your working hours).");
    expect(nextLine({ ...routine, active: false })).toContain("Paused");
    const html = renderToStaticMarkup(React.createElement(RoutineList, { routines: [routine], busy: null, onToggle: () => undefined }));
    expect(html).toContain("Belajar Python: Tue, Thu, 07:00–08:00");
    expect(html).toContain("Pause");
    expect(renderToStaticMarkup(React.createElement(RoutineList, { routines: [], busy: null, onToggle: () => undefined }))).toContain("setiap Selasa dan Kamis");
  });
  it("reports saved routines after a request", () => {
    expect(workMessage(job("succeeded", { routines: ["Belajar Python: Tue, Thu, 07:00–08:00"], blocks_scheduled: 2 })))
      .toContain("Saved 1 routine(s): Belajar Python: Tue, Thu, 07:00–08:00.");
  });
  it("proxies only top-up and pause/resume, and runs the booking job", async () => {
    const post = (path: string[], body?: unknown) => ROUTINE_POST(new NextRequest("http://localhost", { method: "POST", body: body ? JSON.stringify(body) : undefined }), { params: Promise.resolve({ path }) });
    expect((await post(["top-up"], { request_key: key })).status).toBe(202);
    expect(after).toHaveBeenCalled();
    expect((await post([key, "pause"])).status).toBe(200);
    expect((await post([key, "delete"])).status).toBe(404);
    expect((await post(["top-up"], { request_key: "x" })).status).toBe(400);
  });
});

describe("email notifications", () => {
  const settings: Settings = { morning_brief: true, brief_minute: 420, block_reminders: false, reminder_minutes: 10, email: "me@example.test", can_send: false, recent: [] };
  it("validates settings before they reach the API", () => {
    expect(JSON.parse(settingsBody(JSON.stringify({ morning_brief: true, brief_minute: 420, block_reminders: true, reminder_minutes: 15 }))!))
      .toEqual({ morning_brief: true, brief_minute: 420, block_reminders: true, reminder_minutes: 15 });
    for (const bad of [{ morning_brief: "yes", brief_minute: 420, block_reminders: true, reminder_minutes: 15 },
      { morning_brief: true, brief_minute: 1440, block_reminders: true, reminder_minutes: 15 },
      { morning_brief: true, brief_minute: 420, block_reminders: true, reminder_minutes: 7 },
      { morning_brief: true, brief_minute: 420, block_reminders: true, reminder_minutes: 15, to: "someone@else.test" }])
      expect(settingsBody(JSON.stringify(bad))).toBeNull();
  });
  it("asks for the send permission first and explains failures plainly", () => {
    const html = renderToStaticMarkup(React.createElement(NotificationsForm, { settings, saving: false, testing: false, onSave: () => undefined, onTest: () => undefined }));
    expect(html).toContain("allow FocusOS to send email to you");
    expect(html).toContain("(me@example.test) to the same address");
    expect(html).toContain('value="07:00"');
    expect(reason("gmail_send_permission")).toContain("not allowed to send email yet");
    expect(sentLine({ kind: "block_reminder", status: "failed", sent_at: null, safe_error: "provider_unavailable", created_at: "2026-10-17T00:00:00Z" })).toContain("Reminder not sent");
  });
  it("proxies settings and test only", async () => {
    const post = (path: string[], body?: unknown) => NOTIFY_POST(new NextRequest("http://localhost", { method: "POST", body: body ? JSON.stringify(body) : undefined }), { params: Promise.resolve({ path }) });
    expect((await post(["test"])).status).toBe(200);
    expect((await post(["settings"], { morning_brief: true })).status).toBe(400);
    expect((await post(["send"], {})).status).toBe(404);
  });
});

describe("documents and install", () => {
  it("summarizes what a document produced", () => {
    expect(documentMessage(job("succeeded", { tasks_saved: 3, memories_saved: 2 }), "silabus.pdf")).toBe("Saved 3 task(s) and 2 memory item(s) from silabus.pdf.");
    expect(documentMessage(job("succeeded", {}), "foto.jpg")).toContain("found no tasks");
  });
  it("accepts one supported file under the size limit and forwards it as base64", async () => {
    const send = (file: File | string, extra?: Record<string, string>) => {
      const form = new FormData(); form.set("file", file); form.set("request_key", key);
      for (const [name, value] of Object.entries(extra ?? {})) form.set(name, value);
      return DOCUMENT(new NextRequest("http://localhost", { method: "POST", body: form }));
    };
    expect((await send(new File(["%PDF-1.7 hello"], "silabus.pdf", { type: "application/pdf" }))).status).toBe(202);
    const body = JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string);
    expect(body).toMatchObject({ request_key: key, filename: "silabus.pdf", mime_type: "application/pdf" });
    expect(Buffer.from(body.data, "base64").toString()).toBe("%PDF-1.7 hello");
    // Word and Markdown are read too; a .md with no type from the browser is named by its extension.
    expect((await send(new File(["# Tugas 2"], "tugas.md", { type: "" }))).status).toBe(202);
    expect(JSON.parse(vi.mocked(fetch).mock.calls.at(-1)![1]!.body as string).mime_type).toBe("text/markdown");
    expect((await send(new File(["PK"], "tugas.docx", { type: DOCX }))).status).toBe(202);
    expect((await send(new File(["MZ"], "setup.exe", { type: "application/x-msdownload" }))).status).toBe(415);
    // A specific, different type is not overridden by a friendly name.
    expect((await send(new File(["MZ"], "tugas.md", { type: "application/x-msdownload" }))).status).toBe(415);
    expect((await send(new File([new Uint8Array(3_000_001)], "big.pdf", { type: "application/pdf" }))).status).toBe(413);
    expect((await send(new File(["%PDF"], "a.pdf", { type: "application/pdf" }), { extra: "x" })).status).toBe(400);
  });
  it("reads a file's type from its name only when the browser gives none or a generic one", () => {
    expect(fileType({ name: "brief.pdf", type: "application/pdf" })).toBe("application/pdf");
    expect(fileType({ name: "TUGAS.MD", type: "" })).toBe("text/markdown");
    expect(fileType({ name: "tugas.md", type: "text/x-markdown" })).toBe("text/markdown");
    expect(fileType({ name: "tugas.docx", type: "application/octet-stream" })).toBe(DOCX);
    expect(fileType({ name: "catatan.txt", type: "text/plain; charset=utf-8" })).toBe("text/plain");
    expect(fileType({ name: "tugas.doc", type: "application/msword" })).toBeNull();
    expect(fileType({ name: "photo.png", type: "image/gif" })).toBeNull();
  });
  it("can be installed as an app", () => {
    const value = manifest();
    expect(value).toMatchObject({ name: "FocusOS", display: "standalone", start_url: "/" });
    expect(value.icons?.[0].src).toBe("/icon.svg");
  });
});
