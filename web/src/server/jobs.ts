import "server-only";
import { requireServerEnv } from "./env";
export type BackgroundJob = { id: string; status: string; safe_error: string | null; available_at: string; expires_at: string; subject_id: string | null; kind: string };
export async function runBackgroundJob(token: string, job: BackgroundJob, budgetMs = 200_000) {
  const origin = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
  const deadline = Date.now() + budgetMs;
  let current = job;
  while (["queued", "running"].includes(current.status) && Date.now() + 55_000 < deadline) {
    const delay = Math.max(0, new Date(current.available_at).getTime() - Date.now());
    if (delay > 30_000) return; // Scheduler or explicit resume handles long backoff; never spin.
    if (delay) await new Promise(resolve => setTimeout(resolve, delay));
    const response = await fetch(`${origin}/jobs/${job.id}/work`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(55_000), redirect: "error",
    });
    if (!response.ok) return; // Persisted queue is the source of truth after transport errors.
    current = await response.json() as BackgroundJob;
    if (current.status === "running") await new Promise(resolve => setTimeout(resolve, 2000));
  }
}
