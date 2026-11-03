"use client";
import { useCallback, useEffect, useState } from "react";
import { LOCALE } from "../locale";
import { COMPOSE_EVENT } from "../work-composer";

export type Status = "safe" | "tight" | "at_risk";
export type Suggestion = { kind: "book" | "renegotiate" | "defer" | "estimate"; text: string; request?: string; minutes?: number; title?: string; probability?: number };
export type ForecastTask = {
  id: string; title: string; priority: string; deadline: string; probability: number; status: Status; estimated: boolean;
  remaining_minutes: number; need_minutes: { p50: number; p80: number }; booked_minutes: number; free_minutes: number;
  finish: { p50: string | null; p80: string | null }; suggestions: Suggestion[];
};
export type Forecast = {
  generated_at: string; timezone: string; horizon_end: string; calendar: "read" | "unavailable" | "not_needed";
  tasks: ForecastTask[]; overdue: { id: string; title: string; deadline: string }[]; later: number; undated: number;
  unchecked_blocks: number;
  assumptions: { check_ins: number; show_up_rate: number; free_time_use: number; duration_factor: { factor: number; sessions: number }; runs: number };
};

export const STATUS_LABEL: Record<Status, string> = { safe: "On track", tight: "Tight", at_risk: "At risk" };

/** Where a moment sits on the shared now-to-two-weeks scale, as a percentage. */
export function position(value: string | null, start: string, end: string): number {
  if (!value) return 100;
  const from = Date.parse(start), to = Date.parse(end), at = Date.parse(value);
  if (!(to > from)) return 0;
  return Math.min(100, Math.max(0, ((at - from) / (to - from)) * 100));
}

export function duration(minutes: number): string {
  const rounded = Math.max(0, Math.round(minutes / 5) * 5);
  const hours = Math.floor(rounded / 60), rest = rounded % 60;
  return hours ? `${hours}h${rest ? ` ${rest}m` : ""}` : `${rest}m`;
}

function when(value: string, timezone: string): string {
  return new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: timezone }).format(new Date(value));
}

/** What the finish range means in words: the accessible form of the strip. */
export function finishSentence(task: ForecastTask, timezone: string): string {
  const { p50, p80 } = task.finish;
  if (!p50) return "Not likely to be finished within the next two weeks.";
  if (!p80) return `Half the time finished by ${when(p50, timezone)}; often not within two weeks.`;
  return `Likely finished between ${when(p50, timezone)} and ${when(p80, timezone)}.`;
}

/** The numbers the forecast rests on, said plainly, so a percentage is never a black box. */
export function assumptionsText(forecast: Forecast): string {
  const { check_ins: checkIns, show_up_rate: showUp, free_time_use: share, duration_factor: factor, runs } = forecast.assumptions;
  const learned = checkIns
    ? `From your ${checkIns} check-in${checkIns === 1 ? "" : "s"}: work takes about ${factor.factor.toFixed(1)}× the plan and you keep about ${Math.round(showUp * 100)}% of booked blocks.`
    : "No check-ins yet, so this assumes work takes about as long as planned and most booked blocks happen.";
  return `${learned} About ${Math.round(share * 100)}% of free working time is assumed to go to planned work. Simulated ${runs} times.`;
}

function compose(text: string) {
  window.dispatchEvent(new CustomEvent(COMPOSE_EVENT, { detail: { text } }));
}

export function ForecastRow({ task, forecast }: { task: ForecastTask; forecast: Forecast }) {
  const start = forecast.generated_at, end = forecast.horizon_end;
  const from = position(task.finish.p50, start, end), to = position(task.finish.p80, start, end);
  const due = position(task.deadline, start, end);
  const finish = finishSentence(task, forecast.timezone);
  const percent = Math.round(task.probability * 100);
  return <li className="forecast-row" data-status={task.status}>
    <div className="forecast-head">
      <span className="forecast-title">{task.title}</span>
      <span className="forecast-chance"><strong>{percent}%</strong> on time <span className="forecast-status"><i aria-hidden="true" />{STATUS_LABEL[task.status]}</span></span>
    </div>
    <div className="forecast-strip" role="img" title={`${finish} Due ${when(task.deadline, forecast.timezone)}.`}
      aria-label={`${percent}% chance on time. ${finish} Due ${when(task.deadline, forecast.timezone)}.`}>
      <span className={`forecast-range${task.finish.p80 ? "" : " is-open"}`} style={{ left: `${from}%`, width: `${Math.max(0.8, to - from)}%` }} />
      <span className="forecast-due" style={{ left: `${due}%` }} />
    </div>
    <p className="forecast-meta">Due {when(task.deadline, forecast.timezone)} · needs about {duration(task.need_minutes.p50)}
      {task.need_minutes.p80 > task.need_minutes.p50 + 4 ? ` (up to ${duration(task.need_minutes.p80)})` : ""}
      {" · "}{duration(task.booked_minutes)} booked · {duration(task.free_minutes)} free before then</p>
    {task.suggestions.length > 0 && <ul className="forecast-suggestions">{task.suggestions.map((item, index) => <li key={index} data-kind={item.kind}>
      <span>{item.text}</span>
      {item.kind === "book" && item.request && <button type="button" className="secondary-button" onClick={() => compose(item.request as string)}>Write the booking request</button>}
    </li>)}</ul>}
  </li>;
}

export function ForecastView({ forecast }: { forecast: Forecast }) {
  const counts = (["at_risk", "tight", "safe"] as Status[]).map(status => [status, forecast.tasks.filter(task => task.status === status).length] as const);
  const week = position(new Date(Date.parse(forecast.generated_at) + 7 * 86_400_000).toISOString(), forecast.generated_at, forecast.horizon_end);
  return <div className="forecast">
    {forecast.tasks.length === 0 && forecast.overdue.length === 0
      ? <p className="empty">Nothing is due in the next two weeks.{forecast.undated ? ` ${forecast.undated} open task${forecast.undated === 1 ? " has" : "s have"} no deadline.` : ""}</p>
      : <>
        {forecast.tasks.length > 0 && <p className="forecast-summary">{counts.filter(([, count]) => count).map(([status, count]) =>
          <span key={status} data-status={status}><strong>{count}</strong> {STATUS_LABEL[status].toLowerCase()}</span>)}</p>}
        {forecast.calendar === "unavailable" && <p className="forecast-note">Google Calendar could not be read, so every working hour outside booked blocks counts as free. The real chances are likely lower.</p>}
        {forecast.tasks.length > 0 && <>
          <div className="forecast-axis" aria-hidden="true"><span style={{ left: "0%" }}>Now</span><span style={{ left: `${week}%` }}>+1 week</span><span style={{ left: "100%" }}>+2 weeks</span></div>
          <ul className="forecast-list" aria-label="Deadlines in the next two weeks">{forecast.tasks.map(task => <ForecastRow key={task.id} task={task} forecast={forecast} />)}</ul>
          <p className="forecast-legend" aria-hidden="true"><span className="forecast-key-range" /> likely finish (half the time to 4 in 5) <span className="forecast-key-due" /> deadline</p>
        </>}
        {forecast.overdue.length > 0 && <p className="forecast-overdue"><strong>Past the deadline:</strong> {forecast.overdue.map(item => item.title).join(", ")}</p>}
        {forecast.unchecked_blocks > 0 && <p className="forecast-note">{forecast.unchecked_blocks} finished block{forecast.unchecked_blocks === 1 ? "" : "s"} for these tasks {forecast.unchecked_blocks === 1 ? "has" : "have"} no check-in, so {forecast.unchecked_blocks === 1 ? "it counts" : "they count"} as no progress. Checking in sharpens the forecast.</p>}
        <p className="forecast-basis">{assumptionsText(forecast)}{forecast.later ? ` ${forecast.later} later deadline${forecast.later === 1 ? " is" : "s are"} not shown; they cannot take time from these.` : ""}</p>
      </>}
  </div>;
}

export function ForecastPanel() {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    fetch("/api/product/forecast", { cache: "no-store" })
      .then(async response => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : "The forecast is unavailable right now.");
        setForecast(body as Forecast); setError("");
      })
      .catch(cause => setError(cause instanceof Error ? cause.message : "The forecast is unavailable right now."));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("focusos:tasks-changed", load);
    window.addEventListener("focusos:schedule-changed", load);
    return () => { window.removeEventListener("focusos:tasks-changed", load); window.removeEventListener("focusos:schedule-changed", load); };
  }, [load]);
  if (error) return <p role="alert" className="page-alert">{error}</p>;
  if (!forecast) return <p className="empty" aria-busy="true">Simulating the next two weeks…</p>;
  return <ForecastView forecast={forecast} />;
}
