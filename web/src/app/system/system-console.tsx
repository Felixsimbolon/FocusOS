"use client";
import { useCallback, useEffect, useState } from "react";
import { queueJob, describeJob, type Job } from "@/app/jobs/client";
type Diagnostics = {
  database: string;
  queue_ready: boolean;
  lifecycle_ready: boolean;
  configured: Record<string, boolean>;
  encryption_ready: boolean;
  worker_trigger_configured: boolean;
  generation_model: string;
  embedding_model: string;
};
type Run = {
  id: string;
  command: string;
  status: string;
  stage: string;
  safe_error: string | null;
};
export function SystemConsole() {
  const [jobs, setJobs] = useState<Job[]>([]),
    [runs, setRuns] = useState<Run[]>([]),
    [diag, setDiag] = useState<Diagnostics | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setError("");
    try {
      const responses = await Promise.all([
        fetch("/api/product/diagnostics", { cache: "no-store" }),
        fetch("/api/jobs", { cache: "no-store" }),
        fetch("/api/product/history", { cache: "no-store" }),
      ]);
      const values = await Promise.all(responses.map((r) => r.json()));
      if (responses[0].ok) setDiag(values[0]);
      if (responses[1].ok) setJobs(values[1]);
      if (responses[2].ok) setRuns(values[2]);
      if (responses.some((r) => !r.ok))
        setError(
          "Some system data is unavailable. Check migrations and backend configuration.",
        );
    } catch {
      setError("System data unavailable. Try again.");
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 10_000);
    return () => clearInterval(timer);
  }, [load]);
  async function act(job: Job, action: "resume" | "cancel") {
    setBusy(true);
    try {
      const r = await fetch(`/api/jobs/${job.id}/${action}`, {
        method: "POST",
      });
      if (!r.ok) throw new Error();
      await load();
    } catch {
      setError("Job action unavailable. Reload its status before retrying.");
    } finally {
      setBusy(false);
    }
  }
  async function retry(job: Job) {
    setBusy(true);
    setError("");
    try {
      await queueJob(job.kind, job.subject_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry unavailable.");
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    setBusy(true);
    setError("");
    try {
      const r = await fetch("/api/product/export", { cache: "no-store" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `focusos-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      if (
        Object.values(data.truncated as Record<string, boolean>).some(Boolean)
      )
        setError(
          "Export contains the first 1000 rows per table. At least one table is truncated; use a database backup for full recovery.",
        );
    } catch {
      setError("Export unavailable. Check server migrations.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="workspace">
      {error && <p role="alert">{error}</p>}
      <div className="review-panel">
        <h2>Configuration health</h2>
        <p>
          These checks report configuration and database readiness; they do not
          prove provider access or remaining quota.
        </p>
        {diag && (
          <>
            <p>
              Database: {diag.database}. Queue:{" "}
              {diag.queue_ready ? "ready" : "migration needed"}. Lifecycle:{" "}
              {diag.lifecycle_ready ? "ready" : "migration needed"}.
            </p>
            <p>
              Encryption:{" "}
              {diag.encryption_ready ? "ready" : "configuration needed"}.
              Scheduler trigger:{" "}
              {diag.worker_trigger_configured ? "configured" : "not configured"}
              .
            </p>
            <p>
              Models: {diag.generation_model} / {diag.embedding_model}
            </p>
            <ul>
              {Object.entries(diag.configured).map(([name, ready]) => (
                <li key={name}>
                  {name}: {ready ? "configured" : "missing"}
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="workspace-actions">
          <button onClick={() => void load()}>Refresh</button>
          <button disabled={busy} onClick={() => void download()}>
            Export my data
          </button>
        </div>
        <p>
          Exports contain your saved text and evidence. Keep the downloaded file
          private; OAuth credentials and session tokens are excluded.
        </p>
      </div>
      <h2>Background jobs</h2>
      <p>
        Latest 50 jobs. Cancel stops remaining steps; an in-flight provider
        request can still complete. Expired sessions need a new submission.
      </p>
      {!jobs.length && <p>No saved jobs yet.</p>}
      <div className="workspace-list">
        {jobs.map((j) => (
          <article className="review-card" key={j.id}>
            <h3>
              {j.kind} ? {j.status}
            </h3>
            <p>{describeJob(j)}</p>
            {j.result && (
              <p>
                {Object.entries(j.result)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join(" ? ")}
              </p>
            )}
            <div className="workspace-actions">
              {["failed", "expired", "cancelled"].includes(j.status) &&
                j.kind !== "planning" && (
                  <button disabled={busy} onClick={() => void retry(j)}>
                    Retry with current session
                  </button>
                )}
              {["failed", "expired", "cancelled"].includes(j.status) &&
                j.kind === "planning" && <a href="/agent">Start a new plan</a>}
              {j.kind === "planning" && j.subject_id && (
                <a href={`/agent/${j.subject_id}`}>View plan</a>
              )}
              {["queued", "running"].includes(j.status) && (
                <>
                  <button disabled={busy} onClick={() => void act(j, "resume")}>
                    Resume on server
                  </button>
                  <button disabled={busy} onClick={() => void act(j, "cancel")}>
                    Cancel remaining work
                  </button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>
      <h2>Planning history</h2>
      <p>Latest 50 runs.</p>
      <div className="workspace-list">
        {runs.map((r) => (
          <article className="review-card" key={r.id}>
            <a href={`/agent/${r.id}`}>
              <h3>{r.command}</h3>
            </a>
            <p>
              {r.status} ? {r.stage}
              {r.safe_error ? ` ? ${r.safe_error}` : ""}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
