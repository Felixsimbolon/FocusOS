import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NO_STORE = { "Cache-Control": "no-store" };

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401, headers: NO_STORE });
  const path = (await context.params).path;
  if (path.length !== 2 || !UUID.test(path[0]) || !["confirm", "ignore"].includes(path[1]))
    return NextResponse.json({ error: "Review route not found" }, { status: 404, headers: NO_STORE });
  if (Number(request.headers.get("Content-Length") || 0) > 16384)
    return NextResponse.json({ error: "Review too large" }, { status: 413, headers: NO_STORE });
  const body = await request.text();
  if (new TextEncoder().encode(body).length > 16384)
    return NextResponse.json({ error: "Review too large" }, { status: 413, headers: NO_STORE });
  try { JSON.parse(body); } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400, headers: NO_STORE });
  }
  try {
    const url = new URL("/extractions/" + path.join("/"), requireServerEnv("FOCUSOS_API_URL"));
    const response = await fetch(url, {
      method: "POST", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10_000),
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" }, body,
    });
    if (!response.ok) {
      const status = [400, 401, 404, 409, 422].includes(response.status) ? response.status : 503;
      return NextResponse.json({ error: status === 401 ? "Authentication required" : "Review could not be saved" },
        { status, headers: NO_STORE });
    }
    return NextResponse.json(await response.json(), { headers: NO_STORE });
  } catch {
    return NextResponse.json({ error: "Review service unavailable" }, { status: 503, headers: NO_STORE });
  }
}
