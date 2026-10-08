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
      else if (!Number(finished.result?.tasks_saved) && !Number(finished.result?.memories_saved)) {
        setMessage("");
        setError(Number(finished.result?.imported) > 0 ? "Email processed, but no tasks or facts were found." : "No new eligible email found. Apply the FocusOS label in Gmail, then sync again.");
      }
      requestKey.current = null;
      await refresh();
      window.dispatchEvent(new CustomEvent("focusos:sources-changed", { detail: { sourceId: finished.result?.source_id } }));
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (cause) {
      if (!signal.aborted) setError(cause instanceof Error ? cause.message : "Could not finish organizing. Refresh Home to see saved results.");
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

  return <div className="header-gmail" aria-label="Gmail synchronization">
    <button type="button" disabled={busy}
      onClick={() => {
        if (status?.retry_after && Date.parse(status.retry_after) > Date.now()) { setError("Gmail is temporarily limited. Try again after " + new Date(status.retry_after).toLocaleTimeString()); return; }
        if (status && status.connection_status !== "connected") { setError("Connect or reconnect Google to sync email."); return; }
        void run();
      }} title="Import and organize email labeled FocusOS">{busy ? "Syncing Gmail..." : "Sync Gmail"}</button>
    {(message || error) && <div className="header-notice">
      {error ? <p role="alert">{error}</p> : <p role="status" aria-live="polite">{message}</p>}
      {status?.connection_status !== "connected" && <a href="/settings/connections">Connect Google</a>}
      <button type="button" aria-label="Dismiss Gmail notification" onClick={() => { setError(""); setMessage(""); }}>Dismiss</button>
    </div>}
  </div>;
}
