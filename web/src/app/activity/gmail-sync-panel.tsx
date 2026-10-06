"use client";

import { queueJob } from "@/app/jobs/client";
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
    setBusy(true); setMessage("Queueing selected email...");
    try {
      const job = await queueJob("gmail", null);
      setMessage(`Email sync and organization are running on the server. Follow job ${job.id.slice(0, 8)} in System; you can leave this page.`);
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not start email processing."); }
    finally { setBusy(false); }
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
    {message && <p className="activity-message" role="status">{message} <a href="/system">Job status</a></p>}
  </section>;
}
