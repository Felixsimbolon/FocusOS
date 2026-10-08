import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { followOrganization, organizationMessage } from "../src/app/organization";
import type { Job } from "../src/app/jobs/client";
const job = (status: string): Job => ({ id: "synthetic-id", kind: "gmail", subject_id: null, status, safe_error: null,
  available_at: new Date(Date.now() - 1000).toISOString(), expires_at: new Date(Date.now() + 900000).toISOString(),
  steps: 0, failures: 0, result: { tasks_saved: 2, memories_saved: 3 } });
describe("inline organization", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("fetch", vi.fn()); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  it("does not call a queued source organized", () => {
    expect(organizationMessage(job("queued"))).not.toContain("Organized:");
    expect(organizationMessage(job("succeeded"))).toBe("Organized: 2 tasks, 3 memories");
  });
  it("waits for durable completion and resumes server work without creating another request", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json(job("queued"))).mockResolvedValueOnce(Response.json(job("succeeded")));
    const update = vi.fn();
    const result = followOrganization(job("queued"), update, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(2000);
    expect((await result).status).toBe("succeeded");
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/jobs/synthetic-id/resume", expect.objectContaining({ method: "POST" }));
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/jobs/synthetic-id", expect.objectContaining({ cache: "no-store" }));
    expect(update.mock.calls.at(-1)?.[0].status).toBe("succeeded");
  });
  it("respects provider backoff rather than repeatedly requesting processing", async () => {
    const waiting = { ...job("queued"), available_at: new Date(Date.now() + 60000).toISOString(), safe_error: "gmail_backoff" };
    vi.mocked(fetch).mockResolvedValueOnce(Response.json(job("succeeded")));
    const result = followOrganization(waiting, vi.fn(), new AbortController().signal);
    await vi.advanceTimersByTimeAsync(2000);
    await result;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(organizationMessage(waiting)).toContain("Retrying automatically");
  });
  it("reports an expired session without claiming completion", async () => {
    const result = await followOrganization({ ...job("queued"), expires_at: new Date(Date.now() - 1).toISOString() }, vi.fn(), new AbortController().signal);
    expect(result.status).toBe("expired");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("keeps failed and cancelled results distinct from success", async () => {
    for (const status of ["failed", "cancelled"]) {
      const result = await followOrganization(job(status), vi.fn(), new AbortController().signal);
      expect(result.status).toBe(status);
      expect(organizationMessage(result)).not.toContain("Organized:");
    }
    expect(fetch).not.toHaveBeenCalled();
  });
  it("stops observing when the page is closed without cancelling server work", async () => {
    const tracking = new AbortController(); tracking.abort();
    await expect(followOrganization(job("queued"), vi.fn(), tracking.signal)).rejects.toBeDefined();
    expect(fetch).not.toHaveBeenCalled();
  });
});
