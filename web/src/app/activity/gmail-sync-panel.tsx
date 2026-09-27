"use client";

import { useCallback, useEffect, useState } from "react";

type SyncStatus = {
  connection_status: "not_connected" | "reconnect_required" | "connected";
  mode: "initial" | "history" | null; last_status: string; last_error: string | null;
  retry_after: string | null; last_success_at: string | null; page_pending: boolean;
  source_count: number; ready_count: number; failed_count: number; pending_count: number;
};
type SyncStep = { state: string; imported: number; unavailable: number };
type ProcessStep = {
  state: string; source_id: string | null;
  extraction: { capture?: { tasks_saved: number; memories_saved: number; task_failures: number; memory_failures: number; memory_ids: string[] } } | null;
};

async function read<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "Request failed");
  return data as T;
}

export function GmailSyncPanel() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    const next = await read<SyncStatus>(await fetch("/api/integrations/google/gmail/sync", { cache: "no-store" }));
    setStatus(next);
    return next;
  }, []);
  useEffect(() => { void refresh().catch(() => setMessage("Could not load Gmail status.")); }, [refresh]);

  async function run() {
    setBusy(true); setMessage("Checking labeled email...");
    try {
      const step = await read<SyncStep>(await fetch("/api/integrations/google/gmail/sync", { method: "POST" }));
      if (step.state === "busy" || step.state === "retry_wait" || step.state === "rescan_required") {
        setMessage(step.state === "busy" ? "Another sync is running. Try again shortly." :
          step.state === "retry_wait" ? "Gmail asked us to wait. See retry time below." :
            "Gmail history expired. Press the button again to rescan.");
        await refresh();
        return;
      }
      let processed = 0;
      let tasks = 0;
      let memories = 0;
      let failures = 0;
      const initial = await refresh();
      const limit = Math.min(Math.max(initial.pending_count, step.imported), 5);
      for (let index = 0; index < limit; index++) {
        setMessage("Organizing email " + (index + 1) + " of " + limit + "...");
        const item = await read<ProcessStep>(await fetch("/api/integrations/google/gmail/process-one", { method: "POST" }));
        if (item.state === "no_pending") break;
        processed++;
        if (item.state !== "ready") failures++;
        const capture = item.extraction?.capture;
        tasks += capture?.tasks_saved ?? 0;
        memories += capture?.memories_saved ?? 0;
        failures += (capture?.task_failures ?? 0) + (capture?.memory_failures ?? 0);
        for (const id of capture?.memory_ids ?? []) {
          try { await fetch("/api/memories/" + id + "/embed", { method: "POST" }); }
          catch { /* Memory remains saved; embedding can be retried. */ }
        }
        window.dispatchEvent(new Event("focusos:sources-changed"));
        if (item.state !== "ready" || (capture?.task_failures ?? 0) + (capture?.memory_failures ?? 0) > 0) break;
      }
      const after = await refresh();
      setMessage(processed === 0 ? "Sync complete. No new email needed organizing." :
        "Organized " + processed + " email" + (processed === 1 ? "" : "s") + ": " + tasks + " tasks and " + memories +
        " memories saved." + (failures ? " " + failures + " item(s) need a retry." : "") +
        (after.pending_count > 0 ? " More email remains; run sync again to continue." : ""));
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Gmail sync failed");
      try { await refresh(); } catch { /* Keep the actionable error. */ }
    } finally { setBusy(false); }
  }

  return <section className="review-panel gmail-sync-panel" aria-label="Gmail synchronization">
    <div className="activity-panel-heading"><span className="activity-icon">✉</span><div><h2>Gmail inbox</h2><p>Only email with your <strong>FocusOS</strong> label is imported.</p></div></div>
    {status?.connection_status !== "connected" ? <div className="activity-empty">
      {status?.connection_status === "reconnect_required" ? "Reconnect Google with Gmail read access." : "Connect Google to organize selected email."}
      {" "}<a href="/settings/connections">Connection settings →</a>
    </div> : <>
      <div className="activity-stats">
        <div><strong>{status.source_count}</strong><span>Sources</span></div>
        <div><strong>{status.ready_count}</strong><span>Organized</span></div>
        <div><strong>{status.pending_count}</strong><span>Waiting</span></div>
      </div>
      <div className="gmail-sync-actions">
        <button type="button" disabled={busy || !!(status.retry_after && new Date(status.retry_after).getTime() > Date.now())}
          onClick={() => void run()}>{busy ? "Organizing..." : status.page_pending ? "Continue sync & organize" : "Sync & organize email"}</button>
        <span>Last sync: {status.last_success_at ? new Date(status.last_success_at).toLocaleString() : "Never"}</span>
      </div>
      {status.retry_after && new Date(status.retry_after).getTime() > Date.now() && <p role="status">Try again after {new Date(status.retry_after).toLocaleString()}.</p>}
      {status.last_error && <p role="alert">{status.last_error}</p>}
      {status.failed_count > 0 && <p className="activity-hint">{status.failed_count} source(s) have a failed extraction. Sync & organize will retry when available.</p>}
    </>}
    {message && <p className="activity-message" role="status">{message}</p>}
  </section>;
}
