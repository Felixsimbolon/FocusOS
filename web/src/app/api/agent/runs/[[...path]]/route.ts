import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { describePlanningFailure } from "@/app/agent/planning-feedback";

type Context = { params: Promise<{ path?: string[] }> };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const maxDuration = 60;

async function proxy(request: NextRequest, context: Context, method: "GET" | "POST") {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { path = [] } = await context.params;
  const automatic = path.length === 4 && UUID.test(path[0]) && path[1] === "blocks" && /^(?:[0-9]|1[0-5])$/.test(path[2]) && path[3] === "auto";
  const valid = method === "POST"
    ? path.length === 0 || (path.length === 2 && UUID.test(path[0]) && ["continue", "propose-event"].includes(path[1])) || automatic
    : path.length === 1 && UUID.test(path[0]) || path.length === 2 && UUID.test(path[0]) && ["tools", "audit"].includes(path[1]);
  if (!valid) return NextResponse.json({ error: "Run route not found" }, { status: 404 });
  let body: string | undefined;
  if (method === "POST" && (path.length === 0 || path[1] === "propose-event")) {
    body = await request.text();
    if (body.length > 2048) return NextResponse.json({ error: "Command too large" }, { status: 413 });
  }
  try {
    const origin = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const response = await fetch(origin + "/agent/runs" + (path.length ? "/" + path.join("/") : ""), {
      method, headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
      body, cache: "no-store", signal: AbortSignal.timeout(automatic ? 58000 : 26000),
    });
    if (!response.ok) {
      const status = [401, 404, 409, 422, 503].includes(response.status) ? response.status : 502;
      let error = "Agent run unavailable";
      if (status === 409 && (path[1] === "propose-event" || automatic)) {
        const detail = (await response.json().catch(() => null)) as { detail?: unknown } | null;
        const reasons: Record<string, string> = {
          calendar_write_required: "Calendar write access is missing. Open Google connections and enable Calendar event writes.",
          profile_required: "Scheduling preferences are missing. Save your timezone and working hours in Settings.",
          plan_expired: "This planning run has expired. Start a new plan and prepare the event again.",
          task_changed: "The linked task changed or was completed. Start a new plan for an open task.",
          timed_deadline_required: "This task has a date-only deadline. Set an exact due time, then start a new plan.",
          slot_expired: "The proposed time is no longer available. Start a new plan.",
          plan_stale: "This saved block no longer matches the available slot. Start a new plan.",
          invalid_block: "The proposed work block is unavailable. Start a new plan.",
          automatic_plan_required: "This older run cannot schedule automatically. Start a new plan.",
          plan_not_ready: "Planning is not complete yet. Please wait for the run to finish.",
          block_unavailable: "This work block is unavailable. Start a new plan.",
        };
        error = typeof detail?.detail === "string"
          ? reasons[detail.detail] ?? "Could not prepare this Calendar event. Check its write permission and start a fresh plan."
          : "Could not prepare this Calendar event. Check its write permission and start a fresh plan.";
      } else if (status === 409 && path.length === 0) {
        const detail = await response.json().catch(() => null) as { detail?: unknown } | null;
        error = detail?.detail === "request_options_changed"
          ? describePlanningFailure("request_options_changed")
          : "Save your timezone and working hours in Settings, then submit again.";
      } else if (status === 422) {
        error = "Check the planning inputs, Calendar connection, and scheduling preferences, then retry.";
      } else if (status === 409) {
        error = "Planning context changed. Check Calendar and scheduling preferences, then retry.";
      }
      return NextResponse.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Agent run unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}

export async function GET(request: NextRequest, context: Context) { return proxy(request, context, "GET"); }
export async function POST(request: NextRequest, context: Context) { return proxy(request, context, "POST"); }
