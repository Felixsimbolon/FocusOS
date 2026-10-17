"use client";
import { useEffect, useState } from "react";

type Day = { day: string; calls: number; tokens: number; cost_usd: number | null; errors: number };
type Purpose = { purpose: string; calls: number; errors: number; tokens: number; avg_latency_ms: number };
export type Usage = {
  timezone: string;
  totals: { calls: number; errors: number; rate_limited: number; prompt_tokens: number; output_tokens: number; cost_usd: number | null; p95_latency_ms: number | null };
  today_tokens: number;
  by_day: Day[];
  by_purpose: Purpose[];
  daily_token_budget: number | null;
  budget_used_ratio: number | null;
  cost_configured: boolean;
};

const PURPOSE_LABEL: Record<string, string> = {
  intent: "Understanding requests", extract: "Organizing text", answer: "Answering questions",
  answer_select: "Memory answer (legacy)", plan: "Planning", agent_tasks: "Task lookup",
  embed_memory: "Indexing memories", embed_query: "Search queries", triage: "Email priorities",
  graph: "Knowledge graph", review: "Weekly review", agent: "Agent (experimental)",
};
const number = new Intl.NumberFormat();

/** Seven local days ending today, so days without calls still show as zero. */
export function lastSevenDays(days: Day[], timezone: string, now = new Date()): Day[] {
  const byDay = new Map(days.map(day => [day.day, day]));
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(now);
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(`${today}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() - (6 - index));
    const key = date.toISOString().slice(0, 10);
    return byDay.get(key) ?? { day: key, calls: 0, tokens: 0, cost_usd: null, errors: 0 };
  });
}

export function UsageSummary({ usage }: { usage: Usage }) {
  const days = lastSevenDays(usage.by_day, usage.timezone);
  const peak = Math.max(1, ...days.map(day => day.tokens));
  const peakIndex = days.findIndex(day => day.tokens === peak);
  const tokens = usage.totals.prompt_tokens + usage.totals.output_tokens;
  const errorRate = usage.totals.calls ? Math.round((usage.totals.errors / usage.totals.calls) * 100) : 0;
  const label = (day: Day) => new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: "UTC" }).format(new Date(`${day.day}T12:00:00Z`));
  return <div className="usage-summary">
    <dl className="facts">
      <div><dt>Tokens, 7 days</dt><dd>{number.format(tokens)}</dd></div>
      <div><dt>Estimated cost</dt><dd>{usage.cost_configured && usage.totals.cost_usd != null ? `$${usage.totals.cost_usd.toFixed(4)}` : "Not configured"}</dd></div>
      <div><dt>Errors</dt><dd>{errorRate}%<small>{usage.totals.rate_limited ? ` (${usage.totals.rate_limited} rate-limited)` : ""}</small></dd></div>
      <div><dt>Today vs budget</dt><dd>{usage.daily_token_budget
        ? `${Math.round((usage.budget_used_ratio ?? 0) * 100)}%` : "No limit"}<small>{usage.daily_token_budget ? ` of ${number.format(usage.daily_token_budget)}` : ""}</small></dd></div>
    </dl>
    <figure className="usage-chart">
      <figcaption>Tokens per day ({usage.timezone})</figcaption>
      <div className="usage-bars" role="list">
        {days.map((day, index) => <div key={day.day} className="usage-bar" role="listitem" tabIndex={0}
          aria-label={`${label(day)} ${day.day}: ${number.format(day.tokens)} tokens, ${day.calls} calls, ${day.errors} errors`}
          data-tooltip={`${day.day}: ${number.format(day.tokens)} tokens, ${day.calls} calls${day.errors ? `, ${day.errors} errors` : ""}`}>
          {index === peakIndex && day.tokens > 0 && <span className="usage-bar-value">{number.format(day.tokens)}</span>}
          <span className="usage-bar-fill" style={{ height: `${Math.max(day.tokens ? 4 : 0, (day.tokens / peak) * 100)}%` }} />
          <span className="usage-bar-label">{label(day)}</span>
        </div>)}
      </div>
    </figure>
    {usage.by_purpose.length > 0 ? <table className="usage-table">
      <caption className="sr-only">Model calls by purpose</caption>
      <thead><tr><th scope="col">Purpose</th><th scope="col">Calls</th><th scope="col">Tokens</th><th scope="col">Avg latency</th><th scope="col">Errors</th></tr></thead>
      <tbody>{usage.by_purpose.map(item => <tr key={item.purpose}>
        <th scope="row">{PURPOSE_LABEL[item.purpose] ?? item.purpose}</th><td>{number.format(item.calls)}</td>
        <td>{number.format(item.tokens)}</td><td>{number.format(item.avg_latency_ms)} ms</td><td>{item.errors}</td></tr>)}</tbody>
    </table> : <p className="usage-empty">No AI calls in the last seven days.</p>}
  </div>;
}

export function UsagePanel() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/product/usage", { cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); setUsage(await response.json()); })
      .catch(() => { if (!controller.signal.aborted) setError("Could not load AI usage. Try again later."); });
    return () => controller.abort();
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (!usage) return <p className="usage-empty">Loading usage…</p>;
  return <UsageSummary usage={usage} />;
}
