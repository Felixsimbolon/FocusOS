"use client";
import { useCallback, useEffect, useState } from "react";
import { PaginatedItems } from "../paginated-items";
import { StillWater } from "../art/spots";
type Block = {
  id: string;
  run_id: string;
  task_id: string | null;
  status: string;
  payload: { title: string; start: string; end: string; timezone: string };
  provider_link: string | null;
  cancellation_status: string;
  cancellation_error: string | null;
};
export function ScheduleBoard() {
  const [blocks, setBlocks] = useState<Block[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [selected, setSelected] = useState<Block | null>(null),
    [showPast, setShowPast] = useState(false);
  const load = useCallback(async (clearError = true) => {
    setBusy(true);
    if (clearError) setError("");
    try {
      const r = await fetch("/api/product/focus-blocks", { cache: "no-store" });
      if (!r.ok) throw new Error();
      setBlocks(await r.json());
    } catch {
      setError("Could not load scheduled work. Try again.");
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const refresh = () => { void load(); };
    window.addEventListener("focusos:schedule-changed", refresh);
    return () => window.removeEventListener("focusos:schedule-changed", refresh);
  }, [load]);
  async function cancel(block: Block) {
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`/api/product/focus-blocks/${block.id}/cancel`, {
        method: "POST",
      });
      const result = await r.json();
      if (!r.ok) throw new Error(result.error);
      if (result.status !== "cancelled")
        setError(
          result.status === "changed"
            ? "The event was edited in Google Calendar. FocusOS left it unchanged; open Calendar to manage it."
            : "Cancellation is not confirmed. Retry this same block to reconcile before making a replacement.",
        );
      setSelected(null);
      await load(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancellation unavailable.");
    } finally {
      setBusy(false);
    }
  }
  const visible = blocks
    .filter((b) => showPast || new Date(b.payload.end).getTime() > Date.now())
    .sort((a, b) => Date.parse(a.payload.start) - Date.parse(b.payload.start));
  const dayOf = (b: Block) => new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: b.payload.timezone }).format(new Date(b.payload.start));
  const time = (value: string, zone: string) => new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: zone }).format(new Date(value));
  const items = visible.map((b, index) => {
    const zone = b.payload.timezone;
    const cancelled = b.cancellation_status === "cancelled";
    const pending = !cancelled && (b.status !== "succeeded" || b.cancellation_status !== "none");
    const status = cancelled ? "Cancelled" : b.cancellation_status !== "none" ? `Cancellation ${b.cancellation_status}` : b.status === "succeeded" ? null : b.status;
    const newDay = index % 6 === 0 || dayOf(visible[index - 1]) !== dayOf(b); // 6 = page size: each page names its first day.
    return <li key={b.id} className={`rail-item${cancelled ? " is-cancelled" : ""}${pending ? " is-pending" : ""}`}>
      {newDay && <p className="rail-day">{dayOf(b)}</p>}
      <div className="rail-entry">
        <span className="rail-time"><time dateTime={b.payload.start}>{time(b.payload.start, zone)}</time><time dateTime={b.payload.end}>{time(b.payload.end, zone)}</time></span>
        <div className="rail-body">
          <p className="rail-title">{b.payload.title}</p>
          <p className="rail-meta">{status ? `${status}. ` : ""}{zone}</p>
          <div className="rail-actions">
            {b.provider_link && !cancelled && <a href={b.provider_link} target="_blank" rel="noopener noreferrer">Open Calendar</a>}
            {b.status === "succeeded" && !["cancelled", "changed"].includes(b.cancellation_status) && <button type="button" className="quiet" disabled={busy} onClick={() => setSelected(b)}>{b.cancellation_status === "unknown" ? "Reconcile cancellation" : "Cancel block"}</button>}
          </div>
          {selected?.id === b.id && <div className="confirm" role="region" aria-label="Cancel focus block">
            <p><strong>Cancel this Calendar block?</strong> {b.task_id ? "The task stays on your list. " : ""}After cancellation is confirmed, you can ask for another time.</p>
            <div className="confirm-actions"><button type="button" className="danger" disabled={busy} onClick={() => void cancel(b)}>Cancel Calendar block</button><button type="button" className="quiet" disabled={busy} onClick={() => setSelected(null)}>Keep block</button></div>
          </div>}
        </div>
      </div>
    </li>;
  });
  return <div className="schedule-board" aria-label="Saved scheduled work" aria-busy={busy}>
    <div className="schedule-tools">
      <label className="toggle"><input type="checkbox" checked={showPast} onChange={e => setShowPast(e.target.checked)} />Include past blocks</label>
      <button type="button" className="quiet" disabled={busy} onClick={() => void load()}>{busy ? "Refreshing..." : "Refresh"}</button>
    </div>
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    {!busy && !visible.length ? <div className="empty"><StillWater /><p>{showPast ? "No saved blocks yet." : "Your calendar has room."} Ask for a time in the box above, for example &ldquo;cari waktu besok jam 9-11 untuk menulis&rdquo;.</p><a className="button" href="/#composer">Schedule work</a></div>
      : <PaginatedItems key={String(showPast)} as="ul" label="scheduled work" pageSize={6} className="rail" items={items} />}
    <p className="quiet-line">{visible.length} {showPast ? "saved" : "upcoming"} blocks from your latest 100.</p>
  </div>;
}
