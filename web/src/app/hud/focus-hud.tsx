"use client";
import { useEffect, useRef, useState } from "react";
import { Ridges, Stars } from "../art/ridges";

type WorkingHours = { days: number[]; start_minute: number; end_minute: number };
type Block = { status: string; cancellation_status: string; payload: { title: string; start: string; end: string; timezone: string } };
export type LocalNow = { date: string; minutes: number; weekday: number; label: string };
export type Workday =
  | { kind: "rest" }
  | { kind: "before"; minutesUntil: number }
  | { kind: "during"; progress: number; minutesLeft: number }
  | { kind: "after" };
export type Phase = "dawn" | "day" | "dusk" | "night";

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

/** The sky follows the clock: dawn 05:30–07:30, dusk 17:30–19:30. */
export function phase(minutes: number): Phase {
  if (minutes < 330 || minutes >= 1170) return "night";
  if (minutes < 450) return "dawn";
  if (minutes >= 1050) return "dusk";
  return "day";
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
  return hours ? `${hours} h ${String(rest).padStart(2, "0")} m` : `${rest} m`;
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
    case "before": return `Your working window opens in ${duration(state.minutesUntil)}.`;
    case "during": return `${duration(state.minutesLeft)} left in today's working window.`;
    case "after": return "Your working window has closed. Plan tomorrow, or let it rest.";
  }
}

// The sun's path: the working window spread across the sky, from one ridge to the other.
// Ends sit just above the far ridge so blocks late or early in the day stay visible.
const ARC = { left: 190, right: 1250, base: 236, height: 186 };
export function arcPoint(t: number): [number, number] {
  const clamped = Math.min(1, Math.max(0, t));
  return [ARC.left + (ARC.right - ARC.left) * clamped, ARC.base - ARC.height * Math.sin(Math.PI * clamped)];
}
function arcPath(from: number, to: number): string {
  const steps = Math.max(2, Math.ceil((to - from) * 80));
  return Array.from({ length: steps + 1 }, (_, index) => arcPoint(from + ((to - from) * index) / steps))
    .map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
}

/** Where the sun sits: along the working window while it is open, sinking behind a ridge outside it. */
export function sunTarget(state: Workday | null, minutes: number): { t: number; sink: number } {
  if (!state) return { t: 0, sink: 60 };
  if (state.kind === "during") return { t: state.progress, sink: 0 };
  if (state.kind === "before") return { t: 0, sink: Math.min(90, 30 + state.minutesUntil / 4) };
  if (state.kind === "after") return { t: 1, sink: 70 };
  return { t: Math.min(1, Math.max(0, (minutes - 360) / 720)), sink: 0 };
}

function useEased(target: number, enabled: boolean): number {
  const [value, setValue] = useState(enabled ? 0 : target);
  const from = useRef(enabled ? 0 : target);
  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setValue(target); from.current = target; return; }
    const start = performance.now(), origin = from.current, length = 1800;
    let frame = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / length), eased = 1 - Math.pow(1 - p, 3);
      const next = origin + (target - origin) * eased;
      setValue(next); from.current = next;
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return value;
}

export function FocusHud({ timezone, hours, name }: { timezone: string; hours: WorkingHours; name?: string }) {
  const [now, setNow] = useState<Date | null>(null);
  const [dueToday, setDueToday] = useState<number | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      fetch("/api/tasks/today", { cache: "no-store", signal: controller.signal })
        .then(response => response.ok ? response.json() : null)
        .then(result => { if (result && Array.isArray(result.tasks)) setDueToday(result.tasks.length); })
        .catch(() => { /* The horizon is a summary; the task list shows its own errors. */ });
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
  const sky = local ? phase(local.minutes) : "day";
  useEffect(() => { document.documentElement.dataset.phase = sky; }, [sky]);
  const target = sunTarget(state, local?.minutes ?? 0);
  const t = useEased(target.t, true);
  const sink = useEased(target.sink, true);
  const today = local ? todaysBlocks(blocks, local.date, timezone) : [];
  const focusMinutes = today.reduce((total, block) => total + Math.max(0, block.end - block.start), 0);
  const span = Math.max(1, hours.end_minute - hours.start_minute);
  const along = (minutes: number) => (minutes - hours.start_minute) / span;
  const [sunX, sunY] = arcPoint(t);
  const night = sky === "night";

  const summary = [
    dueToday === null ? null : dueToday ? `${dueToday} ${dueToday === 1 ? "task is" : "tasks are"} due today` : "nothing is due today",
    today.length ? `${today.length} focus ${today.length === 1 ? "block" : "blocks"} booked (${duration(focusMinutes)})` : null,
  ].filter(Boolean).join(", and ");

  return <section className="horizon" aria-label="Today">
    <svg className="horizon-art" viewBox="0 0 1440 420" preserveAspectRatio="xMidYMax slice" role="img"
      aria-label={state ? statusLine(state) : "Today"}>
      <defs>
        <radialGradient id="sun-glow"><stop offset="0%" stopColor="var(--sun)" stopOpacity="0.55" /><stop offset="100%" stopColor="var(--sun)" stopOpacity="0" /></radialGradient>
      </defs>
      {night && <Stars />}
      <path className="arc" d={arcPath(0, 1)} pathLength={1} />
      {today.map((block, index) => {
        const from = Math.max(0, along(block.start)), to = Math.min(1, along(block.end));
        return to > from ? <path key={index} className="arc-block" d={arcPath(from, to)} style={{ animationDelay: `${1.2 + index * 0.15}s` }}>
          <title>{`${block.title}, ${clock(block.start)}–${clock(block.end)}`}</title></path> : null;
      })}
      {night ? <g className="moon" transform="translate(1150 108)"><circle r="22" /><circle className="moon-shadow" r="20" cx="9" cy="-6" /></g>
        : <g className="sun" transform={`translate(${sunX.toFixed(1)} ${(sunY + sink).toFixed(1)})`}>
          <circle r="70" fill="url(#sun-glow)" /><circle className="sun-disc" r="24" /></g>}
      <Ridges />
    </svg>
    <div className="horizon-text">
      <p className="horizon-date">{local ? local.label : "Today"}</p>
      <h1>{local ? greeting(local.minutes) : "Hello"}{name ? `, ${name}` : ""}.</h1>
      <p className="horizon-status">{state ? statusLine(state) : "Reading your day…"}{summary ? ` Right now ${summary}.` : ""}</p>
      {today.length > 0 && <ol className="horizon-blocks" aria-label="Today's focus blocks">
        {today.map((block, index) => <li key={index}><time>{clock(block.start)}</time>{block.title}</li>)}
      </ol>}
    </div>
  </section>;
}
