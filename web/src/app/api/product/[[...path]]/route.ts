import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const maxDuration = 60;
type Context = { params: Promise<{ path?: string[] }> };
async function triageBody(request: NextRequest): Promise<string | null> {
  const raw = await request.text();
  if (raw.length > 100) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || Object.keys(value).some(key => key !== "priority")) return null;
    return ["urgent", "normal", "fyi"].includes(value.priority) ? value.priority : null;
  } catch { return null; }
}
type CheckIn = { outcome: "done" | "partial" | "skipped"; actual_minutes: number | null };
async function checkInBody(request: NextRequest): Promise<CheckIn | null> {
  const raw = await request.text();
  if (raw.length > 500) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Object.keys(value).some(key => !["outcome", "actual_minutes"].includes(key))) return null;
    const { outcome, actual_minutes: minutes } = value;
    if (!["done", "partial", "skipped"].includes(outcome)) return null;
    if (outcome === "skipped") return minutes === null || minutes === undefined ? { outcome, actual_minutes: null } : null;
    return Number.isInteger(minutes) && minutes >= 1 && minutes <= 1440 ? { outcome, actual_minutes: minutes } : null;
  } catch { return null; }
}
async function proxy(
  request: NextRequest,
  context: Context,
  method: "GET" | "POST",
) {
  const token = await getServerAccessToken();
  if (!token)
    return NextResponse.json(
      { error: "Authentication required" },
      { status: 401 },
    );
  const path = (await context.params).path || [];
  const review = path.length === 2 && path[0] === "review" && ["current", "previous"].includes(path[1]);
  const month = path.length === 2 && path[0] === "calendar" && /^\d{4}-(0[1-9]|1[0-2])$/.test(path[1]);
  const valid =
    method === "GET"
      ? review || month || path.length === 1 &&
        ["diagnostics", "history", "export", "focus-blocks", "usage", "estimates", "check-ins", "conflicts", "triage", "graph"].includes(path[0])
      : review || (path.length === 3 &&
          path[0] === "focus-blocks" &&
          UUID.test(path[1]) &&
          ["cancel", "check-in"].includes(path[2])) ||
        (path.length === 2 && path[0] === "triage" && UUID.test(path[1])) ||
        (path.length === 2 && path[0] === "graph" && path[1] === "backfill");
  if (!valid)
    return NextResponse.json(
      { error: "Product route not found" },
      { status: 404 },
    );
  // Only a check-in carries a body, and only its two fields are forwarded.
  let body: string | undefined;
  if (method === "POST" && path[2] === "check-in") {
    const checkIn = await checkInBody(request);
    if (!checkIn)
      return NextResponse.json(
        { error: "Choose finished, not finished or skipped, with minutes from 1 to 1440." },
        { status: 400 },
      );
    body = JSON.stringify(checkIn);
  }
  if (method === "POST" && path[0] === "triage") {
    const priority = await triageBody(request);
    if (!priority)
      return NextResponse.json({ error: "Choose urgent, normal or FYI." }, { status: 400 });
    body = JSON.stringify({ priority });
  }
  try {
    const r = await fetch(
      requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") +
        "/product/" +
        path.join("/"),
      {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(55_000),
      },
    );
    if (!r.ok)
      return NextResponse.json(
        {
          error:
            r.status === 401
              ? "Sign in again."
              : r.status === 409
                ? ["conflicts", "calendar"].includes(path[0])
                  ? "Reconnect Google Calendar to check for conflicts."
                  : path[2] === "check-in"
                  ? "This block is not open for check-in."
                  : "This block cannot be cancelled. Check its Calendar state."
                : "Product data unavailable. Check server configuration and migrations.",
        },
        { status: [401, 409].includes(r.status) ? r.status : 503 },
      );
    const headers: Record<string, string> = { "Cache-Control": "no-store" };
    if (path[0] === "export")
      headers["Content-Disposition"] =
        "attachment; filename=focusos-export.json";
    return NextResponse.json(await r.json(), { headers });
  } catch {
    return NextResponse.json(
      { error: "Product data unavailable." },
      { status: 503 },
    );
  }
}
export async function GET(r: NextRequest, c: Context) {
  return proxy(r, c, "GET");
}
export async function POST(r: NextRequest, c: Context) {
  return proxy(r, c, "POST");
}
