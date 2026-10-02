import { describe, expect, it } from "vitest";
import { buildPlanningRequest, describePlanningFailure } from "../src/app/agent/planning-feedback";

const key = "123e4567-e89b-42d3-a456-426614174000";

describe("planning input and feedback", () => {
  it("leaves duration to the command or task estimate instead of silently using 60 minutes", () => {
    expect(buildPlanningRequest(" Schedule checklist for 30 minutes tomorrow ", "", false, key)).toEqual({
      request_key: key, command: "Schedule checklist for 30 minutes tomorrow", duration_minutes: null,
      allow_split: false, auto_calendar: true,
    });
  });
  it("forwards an explicit whole-minute duration and split preference", () => {
    expect(buildPlanningRequest("Plan checklist", "45", true, key)).toMatchObject({ duration_minutes: 45, allow_split: true });
  });
  it.each(["0", "14", "481", "30.5", "oops"])("rejects an invalid override %s before sending", duration => {
    expect(() => buildPlanningRequest("Plan checklist", duration, false, key)).toThrow("15 and 480");
  });
  it("rejects empty and oversized commands", () => {
    expect(() => buildPlanningRequest("   ", "", false, key)).toThrow();
    expect(() => buildPlanningRequest("x".repeat(1001), "", false, key)).toThrow();
  });
  it("explains known planning failures and hides unknown details", () => {
    expect(describePlanningFailure("planning_timeout")).toContain("too long");
    expect(describePlanningFailure("unknown_task_reference")).toContain("active task");
    expect(describePlanningFailure("private SQL or token content")).not.toContain("private SQL");
  });
});
