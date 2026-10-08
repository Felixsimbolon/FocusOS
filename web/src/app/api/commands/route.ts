import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { runBackgroundJob } from "@/server/jobs";
export const maxDuration = 240;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export async function POST(request: NextRequest) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const raw = await request.text();
  if (raw.length > 8000) return NextResponse.json({ error: "Description too long" }, { status: 413 });
  let input: { text: string; request_key: string };
  try {
    input = JSON.parse(raw);
    if (!input || Object.keys(input).some(key => !["text", "request_key"].includes(key)) ||
      typeof input.text !== "string" || !input.text.trim() || input.text.length > 1000 || !UUID.test(input.request_key)) throw new Error();
  } catch { return NextResponse.json({ error: "Write a description of up to 1,000 characters." }, { status: 400 }); }
  try {
    const response = await fetch(requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") + "/commands", {
      method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: JSON.stringify(input), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) {
      const status = [401, 409, 422, 429].includes(response.status) ? response.status : 503;
      return NextResponse.json({ error: status === 401 ? "Sign in again to continue." : status === 429
        ? "Processing limit reached. Wait before submitting again." : status === 409
        ? "This request changed. Refresh and submit it again." : "Could not start processing. Your description is kept; try again." }, { status });
    }
    const result = await response.json();
    after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* The queue retains progress. */ } });
    return NextResponse.json(result, { status: 202, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Could not start processing. Try again shortly." }, { status: 503 }); }
}
