import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UsageSummary, lastSevenDays, type Usage } from "../src/app/usage/usage-panel";

beforeEach(() => vi.stubGlobal("React", React));
const usage = (changes: Partial<Usage> = {}): Usage => ({
  timezone: "Asia/Jakarta",
  totals: { calls: 20, errors: 2, rate_limited: 1, prompt_tokens: 9000, output_tokens: 1000, cost_usd: null, p95_latency_ms: 2100 },
  today_tokens: 4000,
  by_day: [{ day: "2026-10-14", calls: 12, tokens: 6000, cost_usd: null, errors: 1 }, { day: "2026-10-12", calls: 8, tokens: 4000, cost_usd: null, errors: 1 }],
  by_purpose: [{ purpose: "intent", calls: 12, errors: 1, tokens: 7000, avg_latency_ms: 1800 }, { purpose: "new_purpose", calls: 8, errors: 1, tokens: 3000, avg_latency_ms: 300 }],
  daily_token_budget: null, budget_used_ratio: null, cost_configured: false, ...changes,
});

describe("AI usage panel", () => {
  it("fills missing local days with zero so the week is always seven bars", () => {
    const days = lastSevenDays(usage().by_day, "Asia/Jakarta", new Date("2026-10-14T03:00:00Z"));
    expect(days.map(day => day.day)).toEqual(["2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"]);
    expect(days.map(day => day.tokens)).toEqual([0, 0, 0, 0, 4000, 0, 6000]);
  });
  it("uses the user's day, not UTC, near midnight", () => {
    // 18:30 UTC on the 13th is already the 14th in Jakarta.
    expect(lastSevenDays([], "Asia/Jakarta", new Date("2026-10-13T18:30:00Z")).at(-1)?.day).toBe("2026-10-14");
  });
  it("shows totals, error rate and readable purposes without claiming an unknown cost", () => {
    const html = renderToStaticMarkup(React.createElement(UsageSummary, { usage: usage() }));
    expect(html).toContain(new Intl.NumberFormat().format(10000));
    expect(html).toContain("10%");
    expect(html).toContain("1 rate-limited");
    expect(html).toContain("Not configured");
    expect(html).toContain("No limit");
    expect(html).toContain("Understanding requests");
    expect(html).toContain("new_purpose");
    expect(html.match(/role="listitem"/g)).toHaveLength(7);
    expect(html).toContain('aria-label="');
  });
  it("shows budget progress and cost when configured", () => {
    const html = renderToStaticMarkup(React.createElement(UsageSummary, { usage: usage({
      daily_token_budget: 50000, budget_used_ratio: 0.08, cost_configured: true,
      totals: { ...usage().totals, cost_usd: 0.0123 } }) }));
    expect(html).toContain("8%");
    expect(html).toContain(`of ${new Intl.NumberFormat().format(50000)}`);
    expect(html).toContain("$0.0123");
  });
  it("explains an empty week", () => {
    const html = renderToStaticMarkup(React.createElement(UsageSummary, { usage: usage({ by_purpose: [], by_day: [] }) }));
    expect(html).toContain("No AI calls in the last seven days.");
  });
});
