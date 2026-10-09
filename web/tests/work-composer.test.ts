import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkComposer, workMessage } from "../src/app/work-composer";
import { GmailSyncPanel } from "../src/app/activity/gmail-sync-panel";
import type { Job } from "../src/app/jobs/client";
const job=(status:string,result:Record<string,unknown>={}):Job => ({id:"synthetic",kind:"planning",subject_id:"run",status,result,safe_error:null,steps:0,failures:0,available_at:new Date().toISOString(),expires_at:new Date(Date.now()+900000).toISOString()});
beforeEach(() => vi.stubGlobal("React",React));
describe("inferred composer feedback",() => {
  it("has one text field, no action selector, and explains automatic Calendar writes",() => {
    const html=renderToStaticMarkup(React.createElement(WorkComposer));
    expect(html.match(/<textarea/g)).toHaveLength(1);
    expect(html).not.toContain("<select"); expect(html).not.toContain('type="radio"');
    expect(html).toContain("Calendar requests create events automatically"); expect(html).toContain("30 minutes");
  });
  it("shows multi-task guidance in the same text input and reports all saved items", () => {
    const html = renderToStaticMarkup(React.createElement(WorkComposer));
    expect(html).toContain("a whole list");
    expect(html).toContain("Up to 10 tasks per list");
    expect(html).toContain("Buat task berikut:");
    expect(html.match(/<textarea/g)).toHaveLength(1);
    expect(workMessage(job("succeeded", { tasks_saved: 3, memories_saved: 3 }))).toBe("Saved 3 task(s) and 3 memory item(s).");
    expect(workMessage(job("succeeded", { tasks_saved: 3, memories_saved: 3 }))).not.toContain("Calendar");
  });
  it("explains an incomplete batch without inventing a Calendar or login failure", () => {
    const message = workMessage(job("failed", { message: "Could not identify every task in this list. Your description is kept.", intent: "capture" }));
    expect(message).toContain("every task");
    expect(message).not.toContain("Reconnect");
    expect(message).not.toContain("Sign in");
  });
  it("Gmail is a header button without a jobs panel or source counters",() => {
    const html=renderToStaticMarkup(React.createElement(GmailSyncPanel));
    expect(html).toContain("Sync Gmail"); expect(html).not.toContain("<h2"); expect(html).not.toContain("Jobs"); expect(html).not.toContain("<input");
  });
  it("does not claim success while work remains queued",() => {
    expect(workMessage(job("queued",{tasks_saved:1}))).not.toContain("Saved 1");
    expect(workMessage(job("succeeded",{tasks_saved:1,memories_saved:2}))).toBe("Saved 1 task(s) and 2 memory item(s).");
  });
  it.each(["worker_error", "capture_incomplete", "database_unavailable", "step_limit"])("capture failure %s never recommends reconnecting Google", code => {
    const message = workMessage({ ...job("failed", { intent: "capture", tasks_saved: 1 }), safe_error: code });
    expect(message).not.toContain("Google");
    expect(message).toContain("Already saved: 1");
    expect(message).toContain("kept");
  });
  it("unknown scheduling failure does not invent a Google connection problem", () => {
    expect(workMessage({ ...job("failed", { intent: "schedule" }), safe_error: "worker_error" })).not.toContain("Google connection");
  });
  it("explicit Calendar reconnect error gives targeted connection guidance", () => {
    expect(workMessage({ ...job("failed", { intent: "schedule" }), safe_error: "calendar_reconnect_required" })).toContain("Reconnect Google Calendar");
  });
  it("empty capture is explained, not called organized",() => expect(workMessage(job("succeeded"))).toContain("No tasks or facts"));
  it("an expired processing request preserves results without asking to log in again", () => {
    const message = workMessage(job("expired", { tasks_saved: 1, memories_saved: 2, blocks_scheduled: 1 }));
    expect(message).toContain("processing request expired");
    expect(message).toContain("Already saved: 1");
    expect(message).toContain("Check Calendar before");
    expect(message).not.toContain("Sign in");
  });
  it("failure reports partially saved tasks/events so retry cannot silently duplicate them",() => {
    const message=workMessage(job("failed",{message:"No suitable slot",tasks_saved:1,memories_saved:2,blocks_scheduled:1}));
    expect(message).toContain("No suitable slot"); expect(message).toContain("Already saved: 1"); expect(message).toContain("Check Calendar before retrying");
  });
});
