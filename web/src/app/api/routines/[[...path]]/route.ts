import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { runBackgroundJob } from "@/server/jobs";
export const maxDuration = 240;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Context = { params: Promise<{ path?: string[] }> };

async function forward(token: string, path: string, method: "GET" | "POST", body?: string) {
  return fetch(requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") + path, {
    method, headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20_000),
  });
}

export async function GET(_: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  if ((await context.params).path?.length) return NextResponse.json({ error: "Not found" }, { status: 404 });
  try {
    const response = await forward(token, "/routines", "GET");
    if (!response.ok) return NextResponse.json({ error: "Routines are unavailable." }, { status: response.status === 401 ? 401 : 503 });
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Routines are unavailable." }, { status: 503 }); }
}

/** top-up books this week's occurrences (and runs the job after responding); pause/resume change one routine. */
export async function POST(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const path = (await context.params).path ?? [];
  const topUp = path.length === 1 && path[0] === "top-up";
  const toggle = path.length === 2 && UUID.test(path[0]) && ["pause", "resume"].includes(path[1]);
  if (!topUp && !toggle) return NextResponse.json({ error: "Not found" }, { status: 404 });
  let body: string | undefined;
  if (topUp) {
    try {
      const input = JSON.parse(await request.text());
      if (!input || Object.keys(input).some(key => key !== "request_key") || !UUID.test(input.request_key)) throw new Error();
      body = JSON.stringify({ request_key: input.request_key });
    } catch { return NextResponse.json({ error: "Invalid request." }, { status: 400 }); }
  }
  try {
    const response = await forward(token, `/routines/${path.join("/")}`, "POST", body);
    if (!response.ok) return NextResponse.json({ error: response.status === 404 ? "Routine not found." : "Routines are unavailable." },
      { status: [401, 404].includes(response.status) ? response.status : 503 });
    const result = await response.json();
    if (topUp && result.background_job)
      after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* The queue retains progress. */ } });
    return NextResponse.json(result, { status: topUp ? 202 : 200, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Routines are unavailable." }, { status: 503 }); }
}
