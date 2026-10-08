"use client";
import { useCallback, useEffect, useState } from "react";
import { PaginatedItems } from "../paginated-items";
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
  return <section className="schedule-workspace" aria-label="Saved scheduled work" aria-busy={busy}>
    <div className="schedule-toolbar">
      <label className="schedule-past-toggle"><input type="checkbox" checked={showPast} onChange={e => setShowPast(e.target.checked)} />Include past blocks</label>
      <div className="schedule-toolbar-actions"><button type="button" disabled={busy} onClick={() => void load()}>{busy ? "Refreshing..." : "Refresh"}</button>
        <a className="control-button" href="/#composer">Schedule work</a></div>
    </div>
    <p className="schedule-caption">{visible.length} {showPast ? "saved" : "upcoming"} blocks from your latest 100. Planning also checks other Google Calendar events.</p>
    {error && <p role="alert">{error}</p>}
    {!busy && !visible.length && <div className="schedule-empty"><h3>{showPast ? "No saved blocks" : "Your schedule has room."}</h3><p>Describe the work and a time window in the input above.</p></div>}
    <PaginatedItems key={String(showPast)} label="scheduled work" pageSize={4} className="schedule-list" items={visible.map(b => {
      const date = new Date(b.payload.start);
      const zone = b.payload.timezone;
      const cancelled = b.cancellation_status === "cancelled";
      const status = cancelled ? "Cancelled" : b.cancellation_status !== "none" ? `Cancellation: ${b.cancellation_status}` : b.status === "succeeded" ? "Scheduled" : b.status;
      return <article className={`schedule-row${cancelled ? " is-cancelled" : ""}`} key={b.id}>
        <div className="schedule-date"><span>{new Intl.DateTimeFormat(undefined, { month: "short", timeZone: zone }).format(date)}</span><strong>{new Intl.DateTimeFormat(undefined, { day: "2-digit", timeZone: zone }).format(date)}</strong><span>{new Intl.DateTimeFormat(undefined, { year: "numeric", timeZone: zone }).format(date)}</span></div>
        <div className="schedule-details"><h3>{b.payload.title}</h3>
          <p><time dateTime={b.payload.start}>{new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: zone }).format(date)}</time>{" - "}<time dateTime={b.payload.end}>{new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: zone }).format(new Date(b.payload.end))}</time><span className="schedule-zone">{zone}</span></p>
          <span className={`schedule-status${cancelled ? " status-cancelled" : b.status !== "succeeded" || b.cancellation_status !== "none" ? " status-pending" : ""}`}>{status}</span>
        </div>
        <div className="schedule-row-actions">
          {b.provider_link && !cancelled && <a className="control-button" href={b.provider_link} target="_blank" rel="noopener noreferrer">Open Calendar</a>}
          {b.status === "succeeded" && !["cancelled", "changed"].includes(b.cancellation_status) && <button type="button" disabled={busy} onClick={() => setSelected(b)}>{b.cancellation_status === "unknown" ? "Reconcile cancellation" : "Cancel block"}</button>}
        </div>
      </article>;
    })} />
    {selected && <div className="schedule-cancel-panel" role="region" aria-label="Cancel focus block">
      <h3>Cancel this Calendar block?</h3><p><strong>{selected.payload.title}</strong></p>
      <p>{selected.task_id ? "The task remains active. " : ""}After cancellation is confirmed, you can request another time.</p>
      <div className="schedule-toolbar-actions"><button type="button" disabled={busy} onClick={() => void cancel(selected)}>Cancel Calendar block</button><button type="button" disabled={busy} onClick={() => setSelected(null)}>Keep block</button></div>
    </div>}
  </section>;
}
