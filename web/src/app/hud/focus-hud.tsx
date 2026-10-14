"use client";
import { useEffect, useState } from "react";

type WorkingHours = { days: number[]; start_minute: number; end_minute: number };
type Block = { status: string; cancellation_status: string; payload: { title: string; start: string; end: string; timezone: string } };
export type LocalNow = { date: string; minutes: number; weekday: number; label: string };
export type Workday =
  | { kind: "rest" }
  | { kind: "before"; minutesUntil: number }
  | { kind: "during"; progress: number; minutesLeft: number }
  | { kind: "after" };

/** The current wall-clock in the user's timezone; weekday is 1 (Mon) to 7 (Sun). */
export function localNow(now: Date, timezone: string): LocalNow {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    weekday: "short", hourCycle: "h23",
  }).formatToParts(now).map(part => [part.type, part.value]));
  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday) + 1;
  const label = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: timezone }).format(now);
  return { date: `${parts.year}-${parts.month}-${parts.day}`, minutes: Number(parts.hour) * 60 + Number(parts.minute), weekday, label };
}

export function greeting(minutes: number): string {
  if (minutes < 300) return "Still up";
  if (minutes < 720) return "Good morning";
  if (minutes < 1020) return "Good afternoon";
  if (minutes < 1260) return "Good evening";
  return "Good night";
}

export function workday(now: LocalNow, hours: WorkingHours): Workday {
  if (!hours.days.includes(now.weekday)) return { kind: "rest" };
  if (now.minutes < hours.start_minute) return { kind: "before", minutesUntil: hours.start_minute - now.minutes };
  if (now.minutes >= hours.end_minute) return { kind: "after" };
  const span = hours.end_minute - hours.start_minute;
  return { kind: "during", progress: (now.minutes - hours.start_minute) / span, minutesLeft: hours.end_minute - now.minutes };
}

export function duration(minutes: number): string {
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  return hours ? `${hours}h ${String(rest).padStart(2, "0")}m` : `${rest}m`;
}

function clock(minutes: number): string {
  return `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

/** Today's FocusOS blocks as minute ranges in the user's timezone. */
export function todaysBlocks(blocks: Block[], today: string, timezone: string) {
  return blocks.filter(block => block.status === "succeeded" && block.cancellation_status !== "cancelled")
    .map(block => {
      const start = localNow(new Date(block.payload.start), timezone), end = localNow(new Date(block.payload.end), timezone);
      return { title: block.payload.title, date: start.date, start: start.minutes,
               end: end.date === start.date ? end.minutes : 1440 };
    })
    .filter(block => block.date === today)
    .sort((a, b) => a.start - b.start);
}

function statusLine(state: Workday): string {
  switch (state.kind) {
    case "rest": return "A rest day. Nothing has to happen today.";
    case "before": return `Your focus window opens in ${duration(state.minutesUntil)}.`;
    case "during": return `${duration(state.minutesLeft)} left in today's focus window.`;
    case "after": return "Your focus window is closed. Plan tomorrow, or let it rest.";
  }
}

export function FocusHud({ timezone, hours, name }: { timezone: string; hours: WorkingHours; name?: string }) {
  const [now, setNow] = useState<Date | null>(null);
  const [dueToday, setDueToday] = useState<number | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      fetch("/api/tasks/today", { cache: "no-store", signal: controller.signal })
        .then(response => response.ok ? response.json() : null)
        .then(result => { if (result && Array.isArray(result.tasks)) setDueToday(result.tasks.length); })
        .catch(() => { /* The HUD is a summary; the task list shows its own errors. */ });
      fetch("/api/product/focus-blocks", { cache: "no-store", signal: controller.signal })
        .then(response => response.ok ? response.json() : [])
        .then(result => { if (Array.isArray(result)) setBlocks(result); })
        .catch(() => { /* Scheduled work shows its own errors. */ });
    };
    load();
    window.addEventListener("focusos:tasks-changed", load);
    window.addEventListener("focusos:schedule-changed", load);
    return () => { controller.abort(); window.removeEventListener("focusos:tasks-changed", load); window.removeEventListener("focusos:schedule-changed", load); };
  }, []);

  const local = now ? localNow(now, timezone) : null;
  const state = local ? workday(local, hours) : null;
  const today = local ? todaysBlocks(blocks, local.date, timezone) : [];
  const focusMinutes = today.reduce((total, block) => total + Math.max(0, block.end - block.start), 0);
  const progress = state?.kind === "during" ? state.progress : state?.kind === "after" ? 1 : 0;
  // Timeline spans the working window, widened to include any block outside it.
  const from = Math.min(hours.start_minute, ...today.map(block => block.start));
  const to = Math.max(Math.min(hours.end_minute, 1440), ...today.map(block => block.end));
  const span = Math.max(60, to - from);
  const position = (minutes: number) => `${Math.min(100, Math.max(0, ((minutes - from) / span) * 100))}%`;
  const ticks = Array.from({ length: Math.floor(span / 60) + 1 }, (_, index) => Math.ceil(from / 60) * 60 + index * 60).filter(tick => tick <= to);
  const radius = 52, circumference = 2 * Math.PI * radius;

  return <section className="hud" aria-label="Today at a glance">
    <div className="hud-greeting">
      <span className="hud-eyebrow"><span className="hud-pulse" aria-hidden="true" />{local ? local.label : "Today"} · {timezone}</span>
      <h1>{local ? greeting(local.minutes) : "Hello"}{name ? `, ${name}` : ""}.</h1>
      <p className="hud-status">{state ? statusLine(state) : "Loading your day…"}</p>
      <ul className="hud-chips" aria-label="Today in numbers">
        <li><strong>{dueToday ?? "–"}</strong><span>due today</span></li>
        <li><strong>{today.length}</strong><span>blocks today</span></li>
        <li><strong>{focusMinutes ? duration(focusMinutes) : "0m"}</strong><span>focus booked</span></li>
      </ul>
    </div>

    <div className="hud-ring" role="img" aria-label={state?.kind === "during"
      ? `Focus window ${Math.round(progress * 100)} percent elapsed` : statusLine(state ?? { kind: "rest" })}>
      <svg viewBox="0 0 128 128" aria-hidden="true">
        <defs>
          <linearGradient id="hud-ring-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--accent)" /><stop offset="100%" stopColor="var(--accent-2)" />
          </linearGradient>
        </defs>
        <circle className="hud-ring-track" cx="64" cy="64" r={radius} />
        <circle className="hud-ring-ticks" cx="64" cy="64" r={radius + 9} />
        <circle className="hud-ring-progress" cx="64" cy="64" r={radius} stroke="url(#hud-ring-gradient)"
          strokeDasharray={circumference} strokeDashoffset={circumference * (1 - progress)} />
      </svg>
      <div className="hud-ring-center">
        <span className="hud-clock">{local ? <>{clock(local.minutes).slice(0, 2)}<span className="hud-colon">:</span>{clock(local.minutes).slice(3)}</> : "--:--"}</span>
        <small>{state?.kind === "during" ? `${Math.round(progress * 100)}% of window` : state?.kind === "before" ? "before window" : state?.kind === "after" ? "window closed" : "rest day"}</small>
      </div>
    </div>

    <div className="hud-timeline" aria-label="Today's timeline">
      <div className="hud-timeline-head"><span>Today&apos;s timeline</span><small>{clock(hours.start_minute)} – {hours.end_minute === 1440 ? "24:00" : clock(hours.end_minute)}</small></div>
      <div className="hud-track">
        <div className="hud-window" style={{ left: position(hours.start_minute), right: `calc(100% - ${position(Math.min(hours.end_minute, 1440))})` }} />
        {today.map((block, index) => <div key={index} className="hud-block" style={{ left: position(block.start), width: `calc(${position(block.end)} - ${position(block.start)})` }}
          title={`${block.title} · ${clock(block.start)}–${clock(block.end)}`}><span>{block.title}</span></div>)}
        {local && local.minutes >= from && local.minutes <= to && <div className="hud-now" style={{ left: position(local.minutes) }}><span>now</span></div>}
      </div>
      <div className="hud-ticks" aria-hidden="true">{ticks.map(tick => <span key={tick} style={{ left: position(tick) }}>{clock(tick).slice(0, 2)}</span>)}</div>
      {!today.length && <p className="hud-empty">No focus blocks today. Ask for one below.</p>}
      {today.length > 0 && <ul className="sr-only">{today.map((block, index) => <li key={index}>{block.title}, {clock(block.start)} to {clock(block.end)}</li>)}</ul>}
    </div>
  </section>;
}
