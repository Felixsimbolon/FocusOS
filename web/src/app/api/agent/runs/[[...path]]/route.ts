import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

type Context = { params: Promise<{ path?: string[] }> };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function proxy(request: NextRequest, context: Context, method: "GET" | "POST") {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { path = [] } = await context.params;
  const valid = method === "POST"
    ? path.length === 0 || (path.length === 2 && UUID.test(path[0]) && ["continue", "propose-event"].includes(path[1]))
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
      body, cache: "no-store", signal: AbortSignal.timeout(26000),
    });
    if (!response.ok) {
      const status = [401, 404, 409, 422, 503].includes(response.status) ? response.status : 502;
      return NextResponse.json({ error: status === 409 ? "Connect Google Calendar or save scheduling preferences" : "Agent run unavailable" },
        { status, headers: { "Cache-Control": "no-store" } });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Agent run unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}

export async function GET(request: NextRequest, context: Context) { return proxy(request, context, "GET"); }
export async function POST(request: NextRequest, context: Context) { return proxy(request, context, "POST"); }
