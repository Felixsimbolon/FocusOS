import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { settingsBody } from "@/app/notifications/settings-body";
export const maxDuration = 60;
type Context = { params: Promise<{ path?: string[] }> };

function api(token: string, path: string, method: "GET" | "POST", body?: string) {
  return fetch(requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") + "/notifications/" + path, {
    method, headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(45_000),
  });
}

async function handle(request: NextRequest, context: Context, method: "GET" | "POST") {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const path = (await context.params).path ?? [];
  const route = path.join("/");
  if (!(route === "settings" || (method === "POST" && route === "test"))) return NextResponse.json({ error: "Not found" }, { status: 404 });
  let body: string | undefined;
  if (method === "POST" && route === "settings") {
    const checked = settingsBody(await request.text());
    if (!checked) return NextResponse.json({ error: "Invalid notification settings." }, { status: 400 });
    body = checked;
  }
  try {
    const response = await api(token, route, method, body);
    if (!response.ok) return NextResponse.json({ error: response.status === 429 ? "Three test emails per hour. Try again later." : "Email notifications are unavailable right now." },
      { status: [401, 429].includes(response.status) ? response.status : 503 });
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Email notifications are unavailable right now." }, { status: 503 }); }
}

export async function GET(request: NextRequest, context: Context) { return handle(request, context, "GET"); }
export async function POST(request: NextRequest, context: Context) { return handle(request, context, "POST"); }
