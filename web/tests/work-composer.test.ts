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
  it("Gmail is a header button without a jobs panel or source counters",() => {
    const html=renderToStaticMarkup(React.createElement(GmailSyncPanel));
    expect(html).toContain("Sync Gmail"); expect(html).not.toContain("<h2"); expect(html).not.toContain("Jobs"); expect(html).not.toContain("<input");
  });
  it("does not claim success while work remains queued",() => {
    expect(workMessage(job("queued",{tasks_saved:1}))).not.toContain("Saved 1");
    expect(workMessage(job("succeeded",{tasks_saved:1,memories_saved:2}))).toBe("Saved 1 task(s) and 2 memory item(s).");
  });
  it("empty capture is explained, not called organized",() => expect(workMessage(job("succeeded"))).toContain("No tasks or facts"));
  it("failure reports partially saved tasks/events so retry cannot silently duplicate them",() => {
    const message=workMessage(job("failed",{message:"No suitable slot",tasks_saved:1,memories_saved:2,blocks_scheduled:1}));
    expect(message).toContain("No suitable slot"); expect(message).toContain("Already saved: 1"); expect(message).toContain("Check Calendar before retrying");
  });
});
