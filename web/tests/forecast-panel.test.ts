import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { assumptionsText, duration, finishSentence, ForecastView, position, type Forecast, type ForecastTask } from "../src/app/forecast/forecast-panel";
import { GET } from "../src/app/api/product/[[...path]]/route";
import { getServerAccessToken } from "../src/server/auth/session";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));

const NOW = "2026-11-03T01:00:00+00:00";
const END = "2026-11-17T01:00:00+00:00";
const task = (overrides: Partial<ForecastTask> = {}): ForecastTask => ({
  id: "t1", title: "Slides kewirausahaan", priority: "normal", deadline: "2026-11-06T16:59:00+00:00", probability: 0.42, status: "at_risk",
  estimated: true, remaining_minutes: 240, need_minutes: { p50: 290, p80: 340 }, booked_minutes: 60, free_minutes: 600,
  finish: { p50: "2026-11-06T09:00:00+00:00", p80: "2026-11-07T04:00:00+00:00" },
  suggestions: [{ kind: "book", minutes: 295, text: "Book about 295 more minutes before the deadline.", request: 'Book 4 sessions of 75 minutes for "Slides kewirausahaan" before Friday 06 November 23:59' }],
  ...overrides,
});
const forecast = (overrides: Partial<Forecast> = {}): Forecast => ({
  generated_at: NOW, timezone: "Asia/Jakarta", horizon_end: END, calendar: "read", tasks: [task()], overdue: [], later: 0, undated: 0,
  unchecked_blocks: 0, assumptions: { check_ins: 12, show_up_rate: 0.86, free_time_use: 0.5, duration_factor: { factor: 1.3, sessions: 12 }, runs: 400 },
  ...overrides,
});

beforeEach(() => vi.stubGlobal("React", React));
describe("deadline forecast", () => {
  it("places moments on the shared two-week scale", () => {
    expect(position(NOW, NOW, END)).toBe(0);
    expect(position("2026-11-10T01:00:00+00:00", NOW, END)).toBe(50);
    expect(position("2026-12-01T00:00:00+00:00", NOW, END)).toBe(100);
    expect(position(null, NOW, END)).toBe(100); // not finished inside the horizon
    expect(duration(290)).toBe("4h 50m");
    expect(duration(60)).toBe("1h");
    expect(duration(25)).toBe("25m");
  });

  it("says in words what the bar shows, including work that runs past two weeks", () => {
    expect(finishSentence(task(), "Asia/Jakarta")).toMatch(/^Likely finished between .+ and .+\.$/);
    expect(finishSentence(task({ finish: { p50: null, p80: null } }), "Asia/Jakarta")).toBe("Not likely to be finished within the next two weeks.");
    expect(finishSentence(task({ finish: { p50: NOW, p80: null } }), "Asia/Jakarta")).toContain("often not within two weeks");
  });

  it("states the numbers it rests on, and the cold start honestly", () => {
    expect(assumptionsText(forecast())).toContain("From your 12 check-ins: work takes about 1.3× the plan and you keep about 86% of booked blocks.");
    expect(assumptionsText(forecast({ assumptions: { ...forecast().assumptions, check_ins: 0 } }))).toContain("No check-ins yet");
  });

  it("shows each chance with a status word, the strip's meaning for screen readers, and a ready booking request", () => {
    const html = renderToStaticMarkup(React.createElement(ForecastView, { forecast: forecast() }));
    expect(html).toContain("<strong>42%</strong> on time");
    expect(html).toContain("At risk");
    expect(html).toContain('role="img"');
    expect(html).toMatch(/aria-label="42% chance on time\. Likely finished between/);
    expect(html).toContain("Write the booking request");
    expect(html).toContain("<strong>1</strong> at risk");
  });

  it("warns when Calendar was not read and names overdue work", () => {
    const html = renderToStaticMarkup(React.createElement(ForecastView, { forecast: forecast({ calendar: "unavailable", overdue: [{ id: "o", title: "Laporan", deadline: NOW }], unchecked_blocks: 2 }) }));
    expect(html).toContain("Google Calendar could not be read");
    expect(html).toContain("Past the deadline:</strong> Laporan");
    expect(html).toContain("2 finished blocks for these tasks have no check-in");
  });

  it("says when nothing is due", () => {
    const html = renderToStaticMarkup(React.createElement(ForecastView, { forecast: forecast({ tasks: [], undated: 3 }) }));
    expect(html).toContain("Nothing is due in the next two weeks. 3 open tasks have no deadline.");
  });

  it("is proxied, and a missing profile is explained", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue("session");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "x" }, { status: 409 })));
    const response = await GET(new NextRequest("http://localhost"), { params: Promise.resolve({ path: ["forecast"] }) });
    expect(fetch).toHaveBeenCalledWith("https://api.example.test/product/forecast", expect.anything());
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: "Save your timezone and working hours first." });
  });
});
