import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export const maxDuration = 60;

async function proxy(method: "GET" | "POST") {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  try {
    const origin = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const path = method === "GET" ? "/connections/google/gmail/sync/status" : "/connections/google/gmail/sync";
    const response = await fetch(origin + path, {
      method, headers: { Authorization: "Bearer " + accessToken }, cache: "no-store",
      signal: AbortSignal.timeout(method === "POST" ? 58000 : 10000),
    });
    if (!response.ok) {
      const status = [401, 404, 409, 429, 503].includes(response.status) ? response.status : 502;
      const errors: Record<number, string> = {
        401: "Authentication required", 404: "Create a Gmail label named FocusOS",
        409: "Reconnect Google with Gmail read access", 429: "Gmail rate limit reached",
        502: "Gmail sync failed", 503: "Gmail sync temporarily unavailable",
      };
      return NextResponse.json({ error: errors[status] }, { status, headers: { "Cache-Control": "no-store" } });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Gmail sync unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}

export async function GET() { return proxy("GET"); }
export async function POST() { return proxy("POST"); }
