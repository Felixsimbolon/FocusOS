"use client";

import { queueJob, type Job } from "@/app/jobs/client";
import { activeOrganization, followOrganization, organizationMessage } from "../organization";
import { useCallback, useEffect, useRef, useState } from "react";

type SyncStatus = {
  connection_status: "not_connected" | "reconnect_required" | "connected";
  last_error: string | null; retry_after: string | null; last_success_at: string | null;
  source_count: number; ready_count: number; failed_count: number; pending_count: number;
};
async function read<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Gmail is temporarily unavailable.");
  return data as T;
}

export function GmailSyncPanel() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const requestKey = useRef<string | null>(null);
  const refresh = useCallback(async () => {
    const next = await read<SyncStatus>(await fetch("/api/integrations/google/gmail/sync", { cache: "no-store" }));
    setStatus(next);
    return next;
  }, []);

  const observe = useCallback(async (job: Job, signal: AbortSignal) => {
    setBusy(true);
    try {
      const finished = await followOrganization(job, current => setMessage(organizationMessage(current)), signal);
      if (finished.status !== "succeeded") setError(organizationMessage(finished));
      requestKey.current = null;
      await refresh();
      window.dispatchEvent(new CustomEvent("focusos:sources-changed", { detail: { sourceId: finished.result?.source_id } }));
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (cause) {
      if (!signal.aborted) setError(cause instanceof Error ? cause.message : "Could not finish organizing. Refresh Activity to see saved results.");
    } finally { if (!signal.aborted) setBusy(false); }
  }, [refresh]);

  useEffect(() => {
    const tracking = new AbortController();
    controller.current = tracking;
    void (async () => {
      await refresh();
      const jobs = await read<Job[]>(await fetch("/api/jobs", { cache: "no-store", signal: tracking.signal }));
      const existing = jobs.find(job => job.kind === "gmail" && activeOrganization(job));
      if (existing && !tracking.signal.aborted) await observe(existing, tracking.signal);
    })().catch(cause => { if (!tracking.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load Gmail status."); });
    return () => { tracking.abort(); controller.current?.abort(); };
  }, [observe, refresh]);

  async function run() {
    if (busy) return;
    setBusy(true); setError(""); setMessage("Syncing and organizing...");
    controller.current?.abort();
    const tracking = new AbortController();
    controller.current = tracking;
    try {
      requestKey.current ??= crypto.randomUUID();
      const job = await queueJob("gmail", null, requestKey.current);
      await observe(job, tracking.signal);
    } catch (cause) {
      if (!tracking.signal.aborted) { setError(cause instanceof Error ? cause.message : "Could not sync email."); setBusy(false); }
    }
  }

  return <section className="review-panel gmail-sync-panel" aria-label="Gmail synchronization">
    <div className="activity-panel-heading"><div><h2>Your email, organized</h2><p>One click imports email labeled <strong>FocusOS</strong> and saves its tasks and memories.</p></div></div>
    {status && status.connection_status !== "connected" ? <div className="activity-empty">
      {status.connection_status === "reconnect_required" ? "Reconnect Google to read your selected email." : "Connect Google to get started."}
      {" "}<a href="/settings/connections">Connect Google</a>
    </div> : <>
      {status && <div className="activity-stats">
        <div><strong>{status.source_count}</strong><span>Sources</span></div>
        <div><strong>{status.ready_count}</strong><span>Processed</span></div>
      </div>}
      <div className="gmail-sync-actions">
        <button type="button" disabled={!status || busy || !!(status.retry_after && Date.parse(status.retry_after) > Date.now())}
          onClick={() => void run()}>{busy ? "Organizing..." : "Sync & organize"}</button>
        {status && <span>Last sync: {status.last_success_at ? new Date(status.last_success_at).toLocaleString() : "Never"}</span>}
      </div>
      {status?.retry_after && Date.parse(status.retry_after) > Date.now() && <p role="status">Try again after {new Date(status.retry_after).toLocaleString()}.</p>}
    </>}
    {message && <p className="activity-message" role="status" aria-live="polite">{message}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
