"use client";
import { useCallback, useEffect, useState } from "react";
import { type Job } from "../jobs/client";
import { followOrganization } from "../organization";

export type Routine = { id: string; title: string; summary: string; active: boolean; ends_on: string | null;
  upcoming: { date: string; status: "booking" | "booked" | "failed" }[] };
const TOP_UP_KEY = "focusos-routines-topped-up";

export function nextLine(routine: Routine): string {
  if (!routine.active) return "Paused. Nothing new is booked.";
  const booked = routine.upcoming.filter(item => item.status === "booked").length;
  const failed = routine.upcoming.filter(item => item.status === "failed").length;
  if (!routine.upcoming.length) return "Nothing booked this week yet.";
  return `${booked} booked this week${failed ? `, ${failed} could not fit (busy or outside your working hours)` : ""}.`;
}

export function RoutineList({ routines, busy, onToggle }: { routines: Routine[]; busy: string | null; onToggle: (routine: Routine) => void }) {
  if (!routines.length) return <p className="quiet-line">No routines yet. Write one above, for example &ldquo;belajar Python setiap Selasa dan Kamis jam 7-8&rdquo;.</p>;
  return <ul className="routine-list">{routines.map(routine => <li key={routine.id} className={routine.active ? "" : "is-paused"}>
    <div><p className="routine-summary">{routine.summary}</p><p className="quiet-line">{nextLine(routine)}{routine.ends_on ? ` Ends ${routine.ends_on}.` : ""}</p></div>
    <button type="button" className="quiet" disabled={busy === routine.id} onClick={() => onToggle(routine)}>{routine.active ? "Pause" : "Resume"}</button>
  </li>)}</ul>;
}

export function RoutinesPanel({ today }: { today?: string }) {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const load = useCallback(() => {
    fetch("/api/routines", { cache: "no-store" })
      .then(response => response.ok ? response.json() : [])
      .then(result => setRoutines(Array.isArray(result) ? result : []))
      .catch(() => { /* The list is optional context. */ });
  }, []);
  // Once a day, book the coming week's occurrences that are not booked yet.
  useEffect(() => {
    load();
    const day = today ?? new Date().toISOString().slice(0, 10);
    let last: string | null = null;
    try { last = localStorage.getItem(TOP_UP_KEY); } catch { /* Without storage, top up on every visit; the server never books twice. */ }
    if (last === day) return;
    const controller = new AbortController();
    void (async () => {
      const response = await fetch("/api/routines/top-up", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_key: crypto.randomUUID() }), signal: controller.signal });
      if (!response.ok) return;
      try { localStorage.setItem(TOP_UP_KEY, day); } catch { /* See above. */ }
      const result = await response.json();
      if (!result.background_job) return;
      setNotice("Booking this week's routines…");
      const finished = await followOrganization(result.background_job as Job, () => undefined, controller.signal);
      const blocks = Number(finished.result?.blocks_scheduled || 0);
      setNotice(blocks ? `Booked ${blocks} routine block(s) for this week.` : "No new routine blocks fit this week.");
      window.dispatchEvent(new Event("focusos:schedule-changed"));
      load();
    })().catch(() => { /* A later visit tries again. */ });
    return () => controller.abort();
  }, [load, today]);
  async function toggle(routine: Routine) {
    setBusy(routine.id);
    try {
      const response = await fetch(`/api/routines/${routine.id}/${routine.active ? "pause" : "resume"}`, { method: "POST" });
      if (!response.ok) throw new Error();
      load();
    } catch { setNotice("Could not change this routine. Try again."); }
    finally { setBusy(null); }
  }
  return <div className="routines">
    <p className="section-lede">Recurring activities you asked for. FocusOS books each one up to a week ahead, inside your working hours and only where you are free.</p>
    {notice && <p role="status" className="notice">{notice}</p>}
    <RoutineList routines={routines} busy={busy} onToggle={routine => void toggle(routine)} />
  </div>;
}
