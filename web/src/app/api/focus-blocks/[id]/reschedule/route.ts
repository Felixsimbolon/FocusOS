import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { runBackgroundJob } from "@/server/jobs";
export const maxDuration = 240;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Context = { params: Promise<{ id: string }> };
/** Move one conflicting FocusOS block: the API books new time first, then removes the old block. */
export async function POST(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { id } = await context.params;
  let key: string;
  try {
    const raw = await request.text();
    if (raw.length > 200) throw new Error();
    const input = JSON.parse(raw);
    if (!input || Object.keys(input).some(name => name !== "request_key") || !UUID.test(input.request_key)) throw new Error();
    key = input.request_key;
  } catch { return NextResponse.json({ error: "Invalid request." }, { status: 400 }); }
  if (!UUID.test(id)) return NextResponse.json({ error: "Focus block not found." }, { status: 404 });
  try {
    const response = await fetch(`${requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "")}/commands/reschedule/${id}`, {
      method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: JSON.stringify({ request_key: key }), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) {
      const status = [401, 409, 429].includes(response.status) ? response.status : 503;
      const detail = status === 409 ? await response.json().then(body => body?.detail, () => null) : null;
      return NextResponse.json({ error: status === 401 ? "Sign in again to continue." : typeof detail === "string" && detail.length <= 200
        ? detail : status === 429 ? "Processing limit reached. Wait before trying again." : "Could not move this block. Try again shortly." }, { status });
    }
    const result = await response.json();
    after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* The queue retains progress. */ } });
    return NextResponse.json(result, { status: 202, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Could not move this block. Try again shortly." }, { status: 503 }); }
}
