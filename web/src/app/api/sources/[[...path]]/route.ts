import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { runBackgroundJob } from "@/server/jobs";

export const maxDuration = 240;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NO_STORE = { "Cache-Control": "no-store" };

async function handle(request: NextRequest, segments: string[], method: "GET" | "POST" | "DELETE") {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401, headers: NO_STORE });
  const valid =
    method === "GET"
      ? segments.length === 0 || (segments.length === 1 && UUID.test(segments[0])) ||
        (segments.length === 2 && UUID.test(segments[0]) && segments[1] === "extraction")
      : method === "DELETE" ? segments.length === 1 && UUID.test(segments[0])
      : (segments.length === 1 && segments[0] === "manual") ||
        (segments.length === 2 && UUID.test(segments[0]) && segments[1] === "extract");
  if (!valid) return NextResponse.json({ error: "Source route not found" }, { status: 404, headers: NO_STORE });

  const headers: Record<string, string> = { Authorization: "Bearer " + token };
  let body: string | undefined;
  if (method === "POST" && segments[0] === "manual") {
    const key = request.headers.get("Idempotency-Key");
    if (!key || !UUID.test(key)) return NextResponse.json({ error: "Valid source request key required" }, { status: 400, headers: NO_STORE });
    if (Number(request.headers.get("Content-Length") || 0) > 32768) return NextResponse.json({ error: "Source too large" }, { status: 413, headers: NO_STORE });
    body = await request.text();
    if (new TextEncoder().encode(body).length > 32768) return NextResponse.json({ error: "Source too large" }, { status: 413, headers: NO_STORE });
    try { JSON.parse(body); } catch { return NextResponse.json({ error: "Invalid JSON" }, { status: 400, headers: NO_STORE }); }
    headers["Idempotency-Key"] = key;
    headers["Content-Type"] = "application/json";
  }
  try {
    const url = new URL("/sources" + (segments.length ? "/" + segments.join("/") : ""), requireServerEnv("FOCUSOS_API_URL"));
    if (segments[0] === "manual" && request.nextUrl.searchParams.get("background") === "true") url.searchParams.set("background", "true");
    const response = await fetch(url, {
      method, headers, body, cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout((segments.at(-1) === "extract" || segments[0] === "manual") ? 58_000 : 10_000),
    });
    if (!response.ok) {
      const allowed = [400, 401, 404, 409, 410, 413, 422, 429];
      const status = allowed.includes(response.status) ? response.status : 503;
      return NextResponse.json({ error: status === 401 ? "Authentication required" :
        status === 429 ? "Processing limit reached. The source may already be saved; reload Activity and retry." :
        "Source request could not be completed" },
        { status, headers: NO_STORE });
    }
    const result = await response.json();
    if (method === "POST" && result.background_job) after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* Durable queue supports recovery. */ } });
    return NextResponse.json(result, { headers: NO_STORE });
  } catch {
    return NextResponse.json({ error: "Source service unavailable" }, { status: 503, headers: NO_STORE });
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handle(request, (await context.params).path ?? [], "GET");
}
export async function POST(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handle(request, (await context.params).path ?? [], "POST");
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handle(request, (await context.params).path ?? [], "DELETE");
}
