"use client";
import { LOCALE } from "../locale";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { Dew, Mist, Ridges, Stars } from "../art/ridges";

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
  const label = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long", timeZone: timezone }).format(now);
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

// Dragging the sun previews the light at another hour. The arc is the day's window; the ground past
// either end of it holds four more hours, so the sky can be pulled back to dawn or on into night.
const REACH = 190, EXTRA = 240;
export type DayWindow = { start: number; end: number };

/** The window the arc stands for: working hours, or 06:00 to 18:00 on a rest day. */
export function dayWindow(state: Workday | null, hours: WorkingHours): DayWindow {
  return state?.kind === "rest" ? { start: 360, end: 1080 } : { start: hours.start_minute, end: Math.max(hours.end_minute, hours.start_minute + 1) };
}

export function previewRange(day: DayWindow): [number, number] {
  return [Math.max(0, day.start - EXTRA), Math.min(1439, day.end + EXTRA)];
}

/** The clock time at a horizontal position in the drawing, snapped to five minutes. */
export function minutesAt(x: number, day: DayWindow): number {
  const minutes = x < ARC.left ? day.start - Math.min(1, (ARC.left - x) / REACH) * EXTRA
    : x > ARC.right ? day.end + Math.min(1, (x - ARC.right) / REACH) * EXTRA
    : day.start + ((x - ARC.left) / (ARC.right - ARC.left)) * (day.end - day.start);
  const [low, high] = previewRange(day);
  return Math.min(high, Math.max(low, Math.round(minutes / 5) * 5));
}

/** The inverse of minutesAt: where a clock time sits across the drawing. */
export function xAt(minutes: number, day: DayWindow): number {
  if (minutes < day.start) return ARC.left - Math.min(1, (day.start - minutes) / EXTRA) * REACH;
  if (minutes > day.end) return ARC.right + Math.min(1, (minutes - day.end) / EXTRA) * REACH;
  return ARC.left + ((minutes - day.start) / (day.end - day.start)) * (ARC.right - ARC.left);
}

/** A held sun follows the arc inside the window and sinks toward the ridge outside it, never fully, so it can be grabbed back. */
export function heldSun(minutes: number, day: DayWindow): { t: number; sink: number } {
  if (minutes < day.start) return { t: 0, sink: 30 * Math.min(1, (day.start - minutes) / EXTRA) };
  if (minutes > day.end) return { t: 1, sink: 30 * Math.min(1, (minutes - day.end) / EXTRA) };
  return { t: (minutes - day.start) / (day.end - day.start), sink: 0 };
}

/** Dew lies on the grass from first light until mid-morning. */
export function dewy(minutes: number): boolean {
  return minutes >= 300 && minutes < 570;
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

export function FocusHud({ timezone, hours, name, initialDue, initialBlocks }: { timezone: string; hours: WorkingHours; name?: string;
  initialDue?: number | null; initialBlocks?: Block[] | null }) {
  const [now, setNow] = useState<Date | null>(null);
  const [dueToday, setDueToday] = useState<number | null>(initialDue ?? null);
  const [blocks, setBlocks] = useState<Block[]>(initialBlocks ?? []);
  const skipFirst = useRef(initialDue != null && !!initialBlocks);
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
    if (!skipFirst.current) load();
    skipFirst.current = false;
    window.addEventListener("focusos:tasks-changed", load);
    window.addEventListener("focusos:schedule-changed", load);
    return () => { controller.abort(); window.removeEventListener("focusos:tasks-changed", load); window.removeEventListener("focusos:schedule-changed", load); };
  }, []);

  const [held, setHeld] = useState<number | null>(null);
  const drag = useRef<{ clientX: number; from: number; unitsPerPx: number; moved: boolean } | null>(null);
  const local = now ? localNow(now, timezone) : null;
  const state = local ? workday(local, hours) : null;
  const day = dayWindow(state, hours);
  const shown = held ?? local?.minutes ?? 0;
  const realSky = local ? phase(local.minutes) : "day";
  const sky = held === null ? realSky : phase(held);
  useEffect(() => { document.documentElement.dataset.phase = sky; }, [sky]);
  // A preview belongs to Home: other pages get the real sky back.
  const realSkyRef = useRef(realSky);
  realSkyRef.current = realSky;
  useEffect(() => () => { document.documentElement.dataset.phase = realSkyRef.current; }, []);
  const target = sunTarget(state, local?.minutes ?? 0);
  const easedT = useEased(target.t, true);
  const easedSink = useEased(target.sink, true);
  const holding = held === null ? null : heldSun(held, day);
  const t = holding ? holding.t : easedT;
  const sink = holding ? holding.sink : easedSink;

  function grab(event: PointerEvent<SVGSVGElement>) {
    if (!local || event.button !== 0) return;
    const svg = event.currentTarget, ctm = svg.getScreenCTM();
    if (!ctm) return;
    // On a narrow screen the drawing is cropped, so a drag covers more of the day per pixel.
    const unitsPerPx = 1 / ctm.a, visible = svg.getBoundingClientRect().width * unitsPerPx;
    drag.current = { clientX: event.clientX, from: xAt(shown, day), unitsPerPx: unitsPerPx * Math.max(1, 1440 / visible), moved: false };
    svg.setPointerCapture(event.pointerId);
  }
  function pull(event: PointerEvent<SVGSVGElement>) {
    const current = drag.current;
    if (!current) return;
    const dx = event.clientX - current.clientX;
    if (!current.moved && Math.abs(dx) < 4) return;
    current.moved = true;
    setHeld(minutesAt(current.from + dx * current.unitsPerPx, day));
  }
  function release() { drag.current = null; }
  function nudge(event: KeyboardEvent<SVGGElement>) {
    const [low, high] = previewRange(day);
    const step = event.shiftKey ? 60 : 15;
    const next = event.key === "ArrowLeft" || event.key === "ArrowDown" ? shown - step
      : event.key === "ArrowRight" || event.key === "ArrowUp" ? shown + step
      : event.key === "Home" ? low : event.key === "End" ? high : null;
    if (event.key === "Escape" && held !== null) { event.preventDefault(); setHeld(null); return; }
    if (next === null || !local) return;
    event.preventDefault();
    setHeld(Math.min(high, Math.max(low, next)));
  }
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

  const [low, high] = previewRange(day);
  return <section className="horizon" aria-label="Today">
    <svg className={`horizon-art${night ? " is-night" : ""}${dewy(shown) ? " is-dewy" : ""}${held === null ? "" : " is-held"}`}
      viewBox="0 0 1440 420" preserveAspectRatio="xMidYMax slice" role="group" aria-label="Today's sky"
      onPointerDown={grab} onPointerMove={pull} onPointerUp={release} onPointerCancel={release}>
      <defs>
        <radialGradient id="sun-glow"><stop offset="0%" stopColor="var(--sun)" stopOpacity="0.55" /><stop offset="100%" stopColor="var(--sun)" stopOpacity="0" /></radialGradient>
        <radialGradient id="mist-bank"><stop offset="0%" className="mist-stop" stopOpacity="0.75" /><stop offset="100%" className="mist-stop" stopOpacity="0" /></radialGradient>
      </defs>
      <Stars />
      <path className="arc" d={arcPath(0, 1)} pathLength={1} />
      {today.map((block, index) => {
        const from = Math.max(0, along(block.start)), to = Math.min(1, along(block.end));
        return to > from ? <path key={index} className="arc-block" d={arcPath(from, to)} style={{ animationDelay: `${1.2 + index * 0.15}s` }}>
          <title>{`${block.title}, ${clock(block.start)}–${clock(block.end)}`}</title></path> : null;
      })}
      {night && <g className="moon" transform="translate(1150 108)"><circle r="22" /><circle className="moon-shadow" r="20" cx="9" cy="-6" /></g>}
      <g className="sun" transform={`translate(${sunX.toFixed(1)} ${(sunY + sink).toFixed(1)})`}
        tabIndex={0} role="slider" aria-label="Preview the light at another time" aria-valuemin={low} aria-valuemax={high}
        aria-valuenow={shown} aria-valuetext={clock(shown)} onKeyDown={nudge}>
        <title>Drag the sun to see the light at another time</title>
        <circle r="70" fill="url(#sun-glow)" /><circle className="sun-disc" r="24" />
        {held !== null && <text className="sun-time" y="-40" textAnchor="middle">{clock(held)}</text>}
      </g>
      <Ridges valley={<Mist />} />
      <Dew />
    </svg>
    <div className="horizon-text">
      <p className="horizon-date">{local ? local.label : "Today"}</p>
      <h1>{local ? greeting(local.minutes) : "Hello"}{name ? `, ${name}` : ""}.</h1>
      <p className="horizon-status">{state ? statusLine(state) : "Reading your day…"}{summary ? ` Right now ${summary}.` : ""}</p>
      {today.length > 0 && <ol className="horizon-blocks" aria-label="Today's focus blocks">
        {today.map((block, index) => <li key={index}><time>{clock(block.start)}</time>{block.title}</li>)}
      </ol>}
      {held !== null && <p className="horizon-preview" aria-live="polite">Showing the light at {clock(held)}.{" "}
        <button type="button" className="quiet" onClick={() => setHeld(null)}>Back to now</button></p>}
    </div>
  </section>;
}
