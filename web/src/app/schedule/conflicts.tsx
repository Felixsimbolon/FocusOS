"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { type Job } from "../jobs/client";
import { followOrganization } from "../organization";

export type Conflict = { id: string; title: string; start: string; end: string; timezone: string; conflicts: { start: string; end: string }[] };

export function conflictLine(item: Conflict): string {
  const time = (value: string) => new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: item.timezone }).format(new Date(value));
  const clash = item.conflicts[0];
  return `${item.title}, ${time(item.start)}, now overlaps another event (${time(clash.start)}–${new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: item.timezone }).format(new Date(clash.end))}).`;
}

export function moveResult(job: Job): string {
  const result = job.result || {};
  if (job.status !== "succeeded" || !Number(result.blocks_scheduled))
    return typeof result.message === "string" ? result.message : "Could not find another free time. The block was not changed.";
  return result.replaced === "cancelled" ? "Moved. The new block is on your Calendar and the old one was removed."
    : "The new block was created, but the old one could not be removed. Delete it in Google Calendar.";
}

export function ConflictList({ items, moving, onMove }: { items: Conflict[]; moving: string | null; onMove: (item: Conflict) => void }) {
  if (!items.length) return null;
  return <div className="conflicts" role="region" aria-label="Calendar conflicts">
    <p className="conflicts-title">{items.length === 1 ? "1 focus block now clashes with your Calendar" : `${items.length} focus blocks now clash with your Calendar`}</p>
    <ul>{items.map(item => <li key={item.id}><span>{conflictLine(item)}</span>
      <button type="button" onClick={() => onMove(item)} disabled={moving !== null}>{moving === item.id ? "Moving..." : "Move to next free time"}</button></li>)}</ul>
  </div>;
}

export function Conflicts() {
  const [items, setItems] = useState<Conflict[]>([]);
  const [moving, setMoving] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const tracking = useRef<AbortController | null>(null);
  const load = useCallback(() => {
    fetch("/api/product/conflicts", { cache: "no-store" })
      .then(response => response.ok ? response.json() : [])
      .then(result => setItems(Array.isArray(result) ? result : []))
      .catch(() => { /* Conflict checks are advisory; Scheduled work still loads. */ });
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("focusos:schedule-changed", load);
    return () => { window.removeEventListener("focusos:schedule-changed", load); tracking.current?.abort(); };
  }, [load]);
  async function move(item: Conflict) {
    setMoving(item.id); setNotice("");
    const controller = new AbortController(); tracking.current = controller;
    try {
      const response = await fetch(`/api/focus-blocks/${item.id}/reschedule`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_key: crypto.randomUUID() }), signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not move this block.");
      const finished = await followOrganization(data.background_job as Job, () => undefined, controller.signal);
      setNotice(moveResult(finished));
      window.dispatchEvent(new Event("focusos:schedule-changed"));
    } catch (cause) {
      if (!controller.signal.aborted) setNotice(cause instanceof Error ? cause.message : "Could not move this block.");
    } finally { if (!controller.signal.aborted) setMoving(null); }
  }
  return <>{notice && <p role="status" className="conflicts-notice">{notice}</p>}<ConflictList items={items} moving={moving} onMove={item => void move(item)} /></>;
}
