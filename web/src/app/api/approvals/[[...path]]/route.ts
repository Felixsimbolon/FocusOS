import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

type Context = { params: Promise<{ path?: string[] }> };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function proxy(request: NextRequest, context: Context, method: "GET" | "POST") {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { path = [] } = await context.params;
  const runId = request.nextUrl.searchParams.get("run_id");
  const valid = method === "GET" ? path.length === 0 && !!runId && UUID.test(runId)
    : path.length === 2 && UUID.test(path[0]) && path[1] === "decision";
  if (!valid) return NextResponse.json({ error: "Approval route not found" }, { status: 404 });
  let body: string | undefined;
  if (method === "POST") {
    body = await request.text();
    if (body.length > 128) return NextResponse.json({ error: "Decision too large" }, { status: 413 });
  }
  try {
    const origin = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const suffix = method === "GET" ? `?run_id=${runId}` : `/${path[0]}/decision`;
    const response = await fetch(origin + "/approvals" + suffix, {
      method, headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
      body, cache: "no-store", signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) {
      const status = [401, 409, 503].includes(response.status) ? response.status : 502;
      return NextResponse.json({ error: status === 409 ? "Approval is unavailable or already decided" : "Approval unavailable" },
        { status, headers: { "Cache-Control": "no-store" } });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Approval unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
export async function GET(request: NextRequest, context: Context) { return proxy(request, context, "GET"); }
export async function POST(request: NextRequest, context: Context) { return proxy(request, context, "POST"); }
