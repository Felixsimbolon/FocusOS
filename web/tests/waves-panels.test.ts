import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConflictList, conflictLine, moveResult, type Conflict } from "../src/app/schedule/conflicts";
import { TriageList, triageCounts, type TriageItem } from "../src/app/activity/triage-panel";
import { graphSummary } from "../src/app/knowledge/graph-panel";
import { ReviewView, accuracy, hours, type Review } from "../src/app/review/review-panel";
import type { Job } from "../src/app/jobs/client";

const job = (status: string, result: Record<string, unknown>): Job => ({ id: "j", kind: "planning", subject_id: "r", status, result, safe_error: null,
  steps: 0, failures: 0, available_at: new Date().toISOString(), expires_at: new Date(Date.now() + 900000).toISOString() });
beforeEach(() => vi.stubGlobal("React", React));

describe("calendar conflicts", () => {
  const conflict: Conflict = { id: "a", title: "Write report", start: "2026-10-19T06:00:00Z", end: "2026-10-19T07:00:00Z", timezone: "Asia/Jakarta",
    conflicts: [{ start: "2026-10-19T06:30:00Z", end: "2026-10-19T07:30:00Z" }] };
  it("names the block and offers one move action", () => {
    expect(conflictLine(conflict)).toContain("Write report");
    const html = renderToStaticMarkup(React.createElement(ConflictList, { items: [conflict], moving: null, onMove: () => undefined }));
    expect(html).toContain("1 focus block now clashes");
    expect(html).toContain("Move to next free time");
    expect(renderToStaticMarkup(React.createElement(ConflictList, { items: [], moving: null, onMove: () => undefined }))).toBe("");
  });
  it("reports whether the old block was removed", () => {
    expect(moveResult(job("succeeded", { blocks_scheduled: 1, replaced: "cancelled" }))).toContain("old one was removed");
    expect(moveResult(job("succeeded", { blocks_scheduled: 1, replaced: "unknown" }))).toContain("Delete it in Google Calendar");
    expect(moveResult(job("failed", { blocks_scheduled: 0 }))).toContain("not changed");
  });
});

describe("email priorities", () => {
  const items: TriageItem[] = [
    { source_id: "1", title: "Invoice overdue", received_at: null, priority: "urgent", model_priority: "urgent", reason: "Payment due today.", corrected: false },
    { source_id: "2", title: "Newsletter", received_at: null, priority: "fyi", model_priority: "normal", reason: "x", corrected: true },
  ];
  it("counts and lists priorities with a correction control", () => {
    expect(triageCounts(items)).toEqual({ urgent: 1, normal: 0, fyi: 1 });
    const html = renderToStaticMarkup(React.createElement(TriageList, { items, saving: null, onChange: () => undefined }));
    expect(html).toContain("1 urgent, 0 normal and 1 FYI");
    expect(html).toContain("Payment due today.");
    expect(html).toContain("You set this priority.");
    expect(html.match(/<select/g)).toHaveLength(2);
  });
});

describe("knowledge graph and weekly review", () => {
  it("summarizes the graph honestly when empty", () => {
    expect(graphSummary({ entities: 0, relations: 0, indexed_memories: 0 })).toContain("No memories are connected yet");
    expect(graphSummary({ entities: 4, relations: 3, indexed_memories: 5 })).toContain("4 people, projects and places");
  });
  it("shows only SQL numbers and marks template text", () => {
    const review: Review = { week_start: "2026-10-12", narrative: "You booked 5 blocks.", suggestions: ["Start the overdue task."], narrative_source: "template", saved: true,
      stats: { week_start: "2026-10-12", week_end: "2026-10-18", tasks_created: 7, tasks_completed: 4, tasks_overdue: 1, overdue_titles: ["Revisi bab 2"],
        blocks_scheduled: 5, blocks_cancelled: 0, focus_minutes: 210, focus_by_project: [{ project: "Skripsi", minutes: 120 }],
        check_ins: 3, planned_minutes_checked: 150, actual_minutes_checked: 195, model_calls: 40 } };
    expect(hours(210)).toBe("3h 30m");
    expect(hours(45)).toBe("45m");
    expect(accuracy(review.stats)).toBe("1.3× planned");
    const html = renderToStaticMarkup(React.createElement(ReviewView, { review }));
    for (const text of ["3h 30m", "Skripsi", "Revisi bab 2", "You booked 5 blocks.", "Start the overdue task.", "Written from a template"])
      expect(html).toContain(text);
  });
});
