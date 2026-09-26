"use client";

import { FormEvent, useState } from "react";

type Interval = { start: string; end: string };
type Preview = {
  calendar: string; timezone: string; fetched_at: string; complete: boolean;
  event_count: number; busy_events: { title: string; kind: string; start: string; end: string; recurring: boolean }[];
  free_time: {
    requested_minutes: number; available_minutes: number; allocated_minutes: number;
    shortfall_minutes: number; allow_split: boolean; slots: Interval[]; free_intervals: Interval[];
  };
};

function local(value: string, zone: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: zone })
    .format(new Date(value));
}

export function CalendarAvailability() {
  const [days, setDays] = useState(1);
  const [minutes, setMinutes] = useState(60);
  const [split, setSplit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");

  async function read(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setPreview(null);
    const query = new URLSearchParams({
      days: String(days), duration_minutes: String(minutes), allow_split: String(split),
    });
    try {
      const response = await fetch("/api/integrations/google/calendar/availability?" + query, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "Calendar unavailable");
      if (data.complete !== true) throw new Error("Calendar data is incomplete; no free time was calculated");
      setPreview(data as Preview);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Calendar unavailable");
    } finally { setBusy(false); }
  }

  return <section className="calendar-availability" aria-label="Calendar availability">
    <h2>Calendar schedule and free time</h2>
    <p>Read your primary Calendar and preview slots within saved working hours. This does not create an event.</p>
    <form onSubmit={(event) => void read(event)} className="availability-form">
      <label>Window<select value={days} onChange={(event) => setDays(Number(event.target.value))}>
        <option value={1}>Today</option><option value={7}>Next 7 local days</option>
      </select></label>
      <label>Needed minutes<input type="number" min={1} max={1440} value={minutes}
        onChange={(event) => setMinutes(Number(event.target.value))} required /></label>
      <label className="availability-check"><input type="checkbox" checked={split}
        onChange={(event) => setSplit(event.target.checked)} /> Allow split slots</label>
      <button type="submit" disabled={busy}>{busy ? "Checking..." : "Check availability"}</button>
    </form>
    {error && <p role="alert">{error} <a href="/settings/connections">Connection settings</a></p>}
    {preview && <>
      <p role="status">Calendar: {preview.calendar} · Timezone: {preview.timezone} · Fetched {local(preview.fetched_at, preview.timezone)}</p>
      <h3>Busy schedule ({preview.busy_events.length})</h3>
      {preview.busy_events.length ? <ul>{preview.busy_events.map((item, index) =>
        <li key={index}>{item.title}: {local(item.start, preview.timezone)}–{local(item.end, preview.timezone)}
          {item.kind === "all_day" ? " (all day)" : ""}{item.recurring ? " (recurring)" : ""}</li>)}</ul>
        : <p>No busy events in this window.</p>}
      <h3>Free-time preview</h3>
      <p>{preview.free_time.allocated_minutes} of {preview.free_time.requested_minutes} minutes selected.
        {preview.free_time.shortfall_minutes > 0 ? ` Shortfall: ${preview.free_time.shortfall_minutes} minutes.` : ""}
        {" "}Total free capacity: {preview.free_time.available_minutes} minutes.</p>
      {preview.free_time.slots.length > 0 && <ul>{preview.free_time.slots.map((slot, index) =>
        <li key={index}>{local(slot.start, preview.timezone)}–{local(slot.end, preview.timezone)}</li>)}</ul>}
      {preview.free_time.slots.length === 0 && <p>No slot meets the requested duration under this selection policy.</p>}
      <p>Preview only. Recheck Calendar before any future event proposal or write.</p>
    </>}
  </section>;
}
