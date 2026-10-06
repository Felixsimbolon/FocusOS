export type Job = {
  id: string;
  kind: string;
  subject_id: string | null;
  status: string;
  safe_error: string | null;
  available_at: string;
  expires_at: string;
  steps: number;
  failures: number;
  result: Record<string, unknown> | null;
};
export async function queueJob(
  kind: string,
  subjectId: string | null,
  requestKey = crypto.randomUUID(),
): Promise<Job> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind,
      subject_id: subjectId,
      request_key: requestKey,
    }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Processing unavailable.");
  return result;
}
export function describeJob(job: Job) {
  if (job.status === "expired")
    return "The processing session expired. Sign in and submit again. Check existing Calendar blocks before replanning.";
  if (job.status === "failed")
    return `Processing stopped (${job.safe_error || "unavailable"}). Review the saved results in Activity or Schedule before retrying.`;
  if (job.status === "cancelled")
    return "Remaining work was cancelled. A provider request already in progress may still complete.";
  if (job.status === "succeeded")
    return "Processing completed. Saved results are ready.";
  return job.safe_error
    ? `Waiting to retry (${job.safe_error}). Next attempt: ${new Date(job.available_at).toLocaleString()}.`
    : "Processing on the server. You can leave this page and follow the job in System.";
}
