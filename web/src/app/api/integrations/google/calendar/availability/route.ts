import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export const maxDuration = 60;

export async function GET(request: NextRequest) {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const query = request.nextUrl.searchParams;
  const days = query.get("days") ?? "1";
  const minutes = query.get("duration_minutes") ?? "60";
  const split = query.get("allow_split") ?? "false";
  if (!/^[1-7]$/.test(days) || !/^[0-9]{1,4}$/.test(minutes) ||
      Number(minutes) < 1 || Number(minutes) > 1440 ||
      !["true", "false"].includes(split)) {
    return NextResponse.json({ error: "Invalid availability request" }, { status: 400 });
  }
  const deadline = query.get("deadline_at");
  if (deadline && (deadline.length > 64 || !/^\d{4}-\d\d-\d\dT/.test(deadline))) {
    return NextResponse.json({ error: "Invalid deadline" }, { status: 400 });
  }
  const params = new URLSearchParams({ days, duration_minutes: minutes, allow_split: split });
  if (deadline) params.set("deadline_at", deadline);
  try {
    const origin = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const response = await fetch(origin + "/connections/google/calendar/availability?" + params, {
      headers: { Authorization: "Bearer " + accessToken },
      cache: "no-store", signal: AbortSignal.timeout(58000),
    });
    if (!response.ok) {
      const status = [401, 409, 422, 503].includes(response.status) ? response.status : 502;
      const errors: Record<number, string> = {
        401: "Authentication required",
        409: "Connect Google Calendar and save your scheduling preferences",
        422: "Calendar data is incomplete or invalid; no free time was calculated",
        502: "Calendar read failed", 503: "Calendar temporarily unavailable",
      };
      return NextResponse.json({ error: errors[status] },
        { status, headers: { "Cache-Control": "no-store" } });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Calendar temporarily unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
