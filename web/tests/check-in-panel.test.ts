import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CheckInList, checkInMinutes, estimateMessage, type Estimates } from "../src/app/check-ins/check-in-panel";
import { adjustmentNotes } from "../src/app/work-composer";

const factor = (sessions: number, value: number, applied: boolean) => ({ factor: value, low: value - 0.2, high: value + 0.3, sessions, scope: "overall", applied });
const estimates = (sessions: number, value = 1.4, applied = true): Estimates => ({ overall: factor(sessions, value, applied), projects: {}, min_sessions: 5 });
beforeEach(() => vi.stubGlobal("React", React));
describe("check-ins and adaptive estimates", () => {
  it("records what the work really needs", () => {
    expect(checkInMinutes("done", 60, 75)).toBe(75);
    expect(checkInMinutes("partial", 60, 30)).toBe(90); // spent the block, 30 more minutes needed
    expect(checkInMinutes("skipped", 60, 30)).toBeNull();
    expect(checkInMinutes("done", 60, 0)).toBe(1);
  });
  it("explains the learned factor honestly, including when it is not used yet", () => {
    expect(estimateMessage(estimates(2))).toContain("2 of 5");
    expect(estimateMessage(estimates(9, 1.02, false))).toContain("about as long as planned");
    const learned = estimateMessage(estimates(12));
    expect(learned).toContain("1.4×");
    expect(learned).toContain("12 check-ins");
    expect(learned).toContain("without a duration");
  });
  it("lists blocks to check in with the three outcomes", () => {
    const html = renderToStaticMarkup(React.createElement(CheckInList, { estimates: estimates(1), onSaved: () => undefined,
      blocks: [{ id: "a", title: "Write report", start: "2026-10-16T02:00:00Z", end: "2026-10-16T03:00:00Z", timezone: "Asia/Jakarta", planned_minutes: 60 }] }));
    expect(html).toContain("Write report");
    expect(html).toContain("planned 60 min");
    for (const label of ["Finished", "Not finished", "Skipped"]) expect(html).toContain(label);
    expect(renderToStaticMarkup(React.createElement(CheckInList, { blocks: [], estimates: null, onSaved: () => undefined })))
      .toContain("No finished focus blocks");
  });
  it("tells the user when a booked block differs from the saved estimate", () => {
    const [note] = adjustmentNotes({ estimate_adjustments: [{ title: "Write report", estimate_minutes: 30, booked_minutes: 45, factor: 1.5, sessions: 8 }] });
    expect(note).toContain("Booked 45 min for Write report instead of the 30-min estimate");
    expect(note).toContain("Write a duration to override");
    expect(adjustmentNotes({})).toEqual([]);
  });
});
