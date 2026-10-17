"use client";
import { useCallback, useEffect, useMemo, useState } from "react";

export type CalendarEvent = { id: string; title: string; start: string; end: string; all_day: boolean; focusos: boolean };
type Month = { month: string; timezone: string; events: CalendarEvent[]; truncated: boolean };
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PER_DAY = 3;

export function shiftMonth(month: string, by: number): string {
  const [year, number] = month.split("-").map(Number);
  const next = new Date(Date.UTC(year, number - 1 + by, 1));
  return `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, "0")}`;
}

function addDay(key: string, days: number): string {
  const date = new Date(`${key}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Every day an event touches: all-day events span to their exclusive end, timed ones to their end time. */
export function eventDays(event: CalendarEvent): string[] {
  const first = event.start.slice(0, 10);
  const last = event.all_day ? addDay(event.end.slice(0, 10), -1)
    : event.end.slice(11, 16) === "00:00" && event.end.slice(0, 10) > first ? addDay(event.end.slice(0, 10), -1) : event.end.slice(0, 10);
  const days = [first];
  while (days.length < 42 && days[days.length - 1] < last) days.push(addDay(days[days.length - 1], 1));
  return days;
}

export function byDay(events: CalendarEvent[]): Map<string, CalendarEvent[]> {
  const grouped = new Map<string, CalendarEvent[]>();
  for (const event of events) for (const day of eventDays(event)) grouped.set(day, [...(grouped.get(day) ?? []), event]);
  for (const list of grouped.values()) list.sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start));
  return grouped;
}

/** Weeks of the month, Monday first, padded with the neighbouring months' days. */
export function monthGrid(month: string): string[] {
  const [year, number] = month.split("-").map(Number);
  const first = `${month}-01`;
  const lead = (new Date(Date.UTC(year, number - 1, 1)).getUTCDay() + 6) % 7;
  const length = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const cells = Math.ceil((lead + length) / 7) * 7;
  return Array.from({ length: cells }, (_, index) => addDay(first, index - lead));
}

const label = (key: string, options: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(new Date(`${key}T12:00:00Z`));
const time = (event: CalendarEvent) => event.all_day ? "All day" : event.start.slice(11, 16);

export function MonthGrid({ month, today, events, selected, onSelect, direction }: {
  month: string; today: string; events: CalendarEvent[]; selected: string | null; onSelect: (day: string) => void; direction: number;
}) {
  const grouped = useMemo(() => byDay(events), [events]);
  return <div className={`month-grid${direction < 0 ? " from-left" : direction > 0 ? " from-right" : ""}`} key={month} role="grid" aria-label={label(`${month}-01`, { month: "long", year: "numeric" })}>
    <div className="month-weekdays" role="row">{WEEKDAYS.map(day => <span key={day} role="columnheader">{day}</span>)}</div>
    <div className="month-days">
      {monthGrid(month).map(day => {
        const list = grouped.get(day) ?? [];
        const outside = !day.startsWith(month);
        return <button key={day} type="button" role="gridcell"
          className={`month-day${outside ? " is-outside" : ""}${day === today ? " is-today" : ""}${selected === day ? " is-selected" : ""}`}
          aria-pressed={selected === day} onClick={() => onSelect(day)}
          aria-label={`${label(day, { weekday: "long", month: "long", day: "numeric" })}, ${list.length ? `${list.length} event${list.length === 1 ? "" : "s"}` : "no events"}`}>
          <span className="month-date">{Number(day.slice(8))}</span>
          <span className="month-events" aria-hidden="true">
            {list.slice(0, PER_DAY).map(event => <span key={`${event.id}-${event.start}`} className={`month-event${event.all_day ? " is-all-day" : ""}${event.focusos ? " is-focus" : ""}`}>
              {!event.all_day && <time>{event.start.slice(11, 16)}</time>}{event.title}</span>)}
            {list.length > PER_DAY && <span className="month-more">{list.length - PER_DAY} more</span>}
          </span>
        </button>;
      })}
    </div>
  </div>;
}

export function MonthCalendar({ timezone }: { timezone?: string }) {
  const [start] = useState(() => new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date()));
  const [touch, setTouch] = useState<number | null>(null);
  const [month, setMonth] = useState(start.slice(0, 7));
  const [data, setData] = useState<Month | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(start);
  const [direction, setDirection] = useState(0);
  const load = useCallback((target: string, signal?: AbortSignal) => {
    setLoading(true); setError("");
    fetch(`/api/product/calendar/${target}`, { cache: "no-store", signal })
      .then(async response => { const body = await response.json(); if (!response.ok) throw new Error(body.error || "Calendar is unavailable."); return body as Month; })
      .then(result => setData(result))
      .catch(cause => { if (!signal?.aborted) setError(cause instanceof Error ? cause.message : "Calendar is unavailable."); })
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    load(month, controller.signal);
    const refresh = () => load(month);
    window.addEventListener("focusos:schedule-changed", refresh);
    return () => { controller.abort(); window.removeEventListener("focusos:schedule-changed", refresh); };
  }, [load, month]);
  const go = (by: number) => { setDirection(by); setMonth(current => shiftMonth(current, by)); setSelected(null); };
  const events = data?.month === month ? data.events : [];
  const dayEvents = selected ? (byDay(events).get(selected) ?? []) : [];
  return <div className="month" aria-busy={loading}>
    <div className="month-head">
      <h3>{label(`${month}-01`, { month: "long", year: "numeric" })}</h3>
      <div className="month-nav">
        <button type="button" className="month-arrow" aria-label="Previous month" onClick={() => go(-1)}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M12.5 4.5 7 10l5.5 5.5" /></svg></button>
        <button type="button" className="quiet" onClick={() => { setDirection(month < start.slice(0, 7) ? 1 : -1); setMonth(start.slice(0, 7)); setSelected(start); }} disabled={month === start.slice(0, 7)}>Today</button>
        <button type="button" className="month-arrow" aria-label="Next month" onClick={() => go(1)}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 4.5 13 10l-5.5 5.5" /></svg></button>
      </div>
    </div>
    <p className="month-legend"><span className="legend-focus">Booked by FocusOS</span><span className="legend-other">Everything else in your Google Calendar</span>{loading && <span className="month-loading">Loading…</span>}</p>
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {/* Swipe left or right on the grid to change month. */}
    <div className="month-swipe" onTouchStart={event => setTouch(event.touches[0].clientX)}
      onTouchEnd={event => { if (touch !== null) { const delta = event.changedTouches[0].clientX - touch; if (Math.abs(delta) > 60) go(delta < 0 ? 1 : -1); } setTouch(null); }}>
      <MonthGrid month={month} today={start} events={events} selected={selected} onSelect={setSelected} direction={direction} />
    </div>
    {data?.truncated && <p className="quiet-line">This month has more events than can be shown; the first 600 are listed.</p>}
    {selected && <div className="month-agenda" aria-live="polite">
      <p className="ribbon-detail-day">{label(selected, { weekday: "long", month: "long", day: "numeric" })}</p>
      {dayEvents.length ? <ul>{dayEvents.map(event => <li key={`${event.id}-${event.start}`} className={event.focusos ? "is-focus" : ""}>
        <span className="agenda-time">{time(event)}{!event.all_day && <span>{event.end.slice(11, 16)}</span>}</span><span>{event.title}</span></li>)}</ul>
        : <p className="quiet-line">Nothing on your calendar this day.</p>}
    </div>}
  </div>;
}
