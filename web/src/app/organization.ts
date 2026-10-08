import type { Job } from "./jobs/client";

// Login/reload must only recover work whose original processing session is still valid.
export const activeOrganization = (job: Job) =>
  ["queued", "running"].includes(job.status) && Date.parse(job.expires_at) > Date.now();

export function organizationMessage(job: Job): string {
  const tasks = Number(job.result?.tasks_saved ?? 0);
  const memories = Number(job.result?.memories_saved ?? 0);
  if (job.status === "succeeded") return `Organized: ${tasks} tasks, ${memories} memories`;
  if (job.status === "expired") return "This processing request expired. Your saved results are kept. Start a new request to continue.";
  if (job.status === "cancelled") return "Processing stopped. Results already saved are kept.";
  if (job.status === "failed" && typeof job.result?.message === "string") return job.result.message;
  if (job.status === "failed") return "Could not finish organizing. Your source and any saved results are kept. Try again later.";
  if (job.safe_error === "gmail_backoff") return "Gmail is temporarily limited. Retrying automatically...";
  if (job.safe_error) return "Processing is temporarily unavailable. Retrying automatically...";
  return job.result?.tasks_saved || job.result?.memories_saved
    ? `Saving memories for search... ${tasks} tasks, ${memories} memories`
    : "Syncing and organizing...";
}

async function readJob(response: Response): Promise<Job> {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not check processing. Refresh Home to see saved results.");
  return data as Job;
}

/** Observe durable results; resume schedules server work, never runs individual steps in the browser. */
export async function followOrganization(
  initial: Job,
  onUpdate: (job: Job) => void,
  signal: AbortSignal,
): Promise<Job> {
  let current = initial;
  let lastResume = 0;
  const deadline = Math.min(Date.now() + 15 * 60_000, new Date(initial.expires_at).getTime());
  while (true) {
    signal.throwIfAborted();
    if (["queued", "running"].includes(current.status) &&
        (!activeOrganization(current) || Date.now() >= deadline)) {
      current = { ...current, status: "expired", safe_error: "session_expired" };
    }
    onUpdate(current);
    if (!activeOrganization(current)) return current;
    // Keep long-backoff work moving without sending users to a jobs dashboard.
    if (current.status === "queued" && Date.parse(current.available_at) <= Date.now() && Date.now() - lastResume >= 45_000) {
      lastResume = Date.now();
      await readJob(await fetch(`/api/jobs/${current.id}/resume`, { method: "POST", signal }));
    }
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(signal.reason); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 2000);
      signal.addEventListener("abort", abort, { once: true });
    });
    current = await readJob(await fetch(`/api/jobs/${current.id}`, { cache: "no-store", signal }));
  }
}
