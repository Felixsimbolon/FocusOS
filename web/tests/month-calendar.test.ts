import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MonthGrid, byDay, eventDays, monthGrid, shiftMonth, type CalendarEvent } from "../src/app/schedule/month-calendar";
import { GET } from "../src/app/api/product/[[...path]]/route";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));

const event = (id: string, start: string, end: string, extra: Partial<CalendarEvent> = {}): CalendarEvent =>
  ({ id, title: id, start, end, all_day: false, focusos: false, ...extra });
beforeEach(() => vi.stubGlobal("React", React));

describe("month calendar", () => {
  it("moves across year boundaries", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });
  it("lays out whole Monday-first weeks", () => {
    const days = monthGrid("2026-10"); // 1 October 2026 is a Thursday
    expect(days.length % 7).toBe(0);
    expect(days[0]).toBe("2026-09-28");
    expect(days[3]).toBe("2026-10-01");
    expect(days).toContain("2026-10-31");
  });
  it("places multi-day and all-day events on every day they cover", () => {
    expect(eventDays(event("trip", "2026-10-20", "2026-10-23", { all_day: true }))).toEqual(["2026-10-20", "2026-10-21", "2026-10-22"]);
    expect(eventDays(event("late", "2026-10-20T22:00:00+07:00", "2026-10-21T00:00:00+07:00"))).toEqual(["2026-10-20"]);
    const grouped = byDay([event("b", "2026-10-20T13:00:00+07:00", "2026-10-20T14:00:00+07:00"), event("a", "2026-10-20", "2026-10-21", { all_day: true })]);
    expect(grouped.get("2026-10-20")!.map(item => item.id)).toEqual(["a", "b"]);
  });
  it("shows events in their day, FocusOS blocks marked, and a count past three", () => {
    const events = [
      event("Standup", "2026-10-20T09:30:00+07:00", "2026-10-20T09:45:00+07:00"),
      event("Write report", "2026-10-20T10:00:00+07:00", "2026-10-20T11:00:00+07:00", { focusos: true }),
      event("Lunch", "2026-10-20T12:00:00+07:00", "2026-10-20T13:00:00+07:00"),
      event("Review", "2026-10-20T15:00:00+07:00", "2026-10-20T16:00:00+07:00"),
    ];
    const html = renderToStaticMarkup(React.createElement(MonthGrid, { month: "2026-10", today: "2026-10-17", events, selected: null, onSelect: () => undefined, direction: 0 }));
    expect(html).toContain("09:30");
    expect(html).toContain("month-event is-focus");
    expect(html).toContain("1 more");
    expect(html).toContain("Tuesday, October 20, 4 events");
    expect(html).toContain("month-day is-today");
  });
  it("proxies only well-formed months", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ events: [] })));
    const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) });
    expect((await GET(new NextRequest("http://localhost"), ctx(["calendar", "2026-10"]))).status).toBe(200);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("https://api.example.test/product/calendar/2026-10");
    for (const month of ["2026-13", "26-10", "2026-10-01"])
      expect((await GET(new NextRequest("http://localhost"), ctx(["calendar", month]))).status).toBe(404);
  });
});
