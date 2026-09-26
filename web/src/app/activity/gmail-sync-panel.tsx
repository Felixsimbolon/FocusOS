"use client";

import { useCallback, useEffect, useState } from "react";

type SyncStatus = {
  connection_status: "not_connected" | "reconnect_required" | "connected";
  label_name: string; mode: "initial" | "history" | null;
  last_status: string; last_error: string | null; retry_after: string | null;
  last_attempt_at: string | null; last_success_at: string | null;
  lease_until: string | null; pending_staged: number; page_pending: boolean;
  source_count: number; ready_count: number; failed_count: number; pending_count: number;
};
type SyncStep = { state: string; mode: string | null; imported: number; unavailable: number };
type ProcessStep = { state: string; source_id: string | null };

async function responseJson<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "Request failed");
  return data as T;
}

function timestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

export function GmailSyncPanel() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    const data = await responseJson<SyncStatus>(await fetch("/api/integrations/google/gmail/sync", { cache: "no-store" }));
    setStatus(data);
  }, []);

  useEffect(() => {
    void refresh().catch((error) => setMessage(error instanceof Error ? error.message : "Could not load Gmail status"));
  }, [refresh]);

  async function run(kind: "sync" | "process") {
    setBusy(true); setMessage("");
    try {
      if (kind === "sync") {
        const step = await responseJson<SyncStep>(await fetch("/api/integrations/google/gmail/sync", { method: "POST" }));
        setMessage(step.state === "busy" ? "Another sync is running. Try again shortly." :
          step.state === "retry_wait" ? "Gmail asked us to wait. See retry time below." :
          step.state === "rescan_required" ? "Gmail history expired. A bounded full scan is ready; press Continue." :
          `Sync ${step.state}: ${step.imported} source(s) saved, ${step.unavailable} unavailable. ${step.state === "partial" ? "Press Continue for the next page." : ""}`);
      } else {
        const step = await responseJson<ProcessStep>(await fetch("/api/integrations/google/gmail/process-one", { method: "POST" }));
        setMessage(step.state === "no_pending" ? "No Gmail source is waiting for extraction." :
          `Extraction ${step.state}. Review the source below.`);
      }
      await refresh();
      window.dispatchEvent(new Event("focusos:sources-changed"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Gmail action failed");
      try { await refresh(); } catch { /* Preserve the actionable error. */ }
    } finally { setBusy(false); }
  }

  return <section className="review-panel gmail-sync-panel" aria-label="Gmail synchronization">
    <h2>Gmail selected-label sync</h2>
    <p>Only messages with your <strong>FocusOS</strong> Gmail label are selected. Each click handles one bounded page or one extraction; progress resumes from the saved checkpoint.</p>
    {!status && <p role="status">{message || "Loading Gmail status..."}</p>}
    {status && status.connection_status !== "connected" && <p role="status">
      {status.connection_status === "not_connected" ? "Google is not connected." : "Reconnect Google with Gmail read access."}
      {" "}<a href="/settings/connections">Open connection settings</a>
    </p>}
    {status?.connection_status === "connected" && <>
      <p>Mode: {status.mode ?? "not started"} · Last sync: {status.last_status} · Last success: {timestamp(status.last_success_at)}</p>
      <p>Saved sources: {status.source_count} · Ready for review: {status.ready_count} · Waiting for extraction: {status.pending_count} · Failed: {status.failed_count}</p>
      {status.pending_staged > 0 && <p>{status.pending_staged} message ID(s) staged for the next page.</p>}
      {status.retry_after && new Date(status.retry_after).getTime() > Date.now() &&
        <p role="status">Retry after {timestamp(status.retry_after)}.</p>}
      {status.last_error && <p role="alert">Last sync error: {status.last_error}</p>}
      <div className="gmail-sync-actions">
        <button type="button" disabled={busy || (status.retry_after !== null && new Date(status.retry_after).getTime() > Date.now())}
          onClick={() => void run("sync")}>{status.page_pending ? "Continue sync" : "Sync Now"}</button>
        <button type="button" className="secondary-button" disabled={busy || status.pending_count === 0}
          onClick={() => void run("process")}>Process one source</button>
      </div>
      <p>Open Gmail to create the <strong>FocusOS</strong> label and apply it to messages you choose. Label missing? Sync Now will explain.</p>
      {message && <p role="status">{message}</p>}
    </>}
  </section>;
}
