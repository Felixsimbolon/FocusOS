import { describe, expect, it } from "vitest";
import { deadlineDay } from "../src/app/tasks/deadline-calendar";

describe("deadline calendar day grouping", () => {
  it("keeps a date-only deadline on its stated day", () => {
    expect(deadlineDay({ due_kind: "date", due_date: "2026-10-02", due_at: null }, "Asia/Jakarta"))
      .toBe("2026-10-02");
  });
  it("places timed deadlines on the user's local calendar day", () => {
    const task = { due_kind: "datetime" as const, due_date: null, due_at: "2026-10-01T18:30:00Z" };
    expect(deadlineDay(task, "Asia/Jakarta")).toBe("2026-10-02");
    expect(deadlineDay(task, "America/Los_Angeles")).toBe("2026-10-01");
  });
  it("does not place tasks without a deadline on the calendar", () => {
    expect(deadlineDay({ due_kind: "none", due_date: null, due_at: null }, "Asia/Jakarta"))
      .toBeNull();
  });
});