import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export const maxDuration = 60;

export async function POST() {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  try {
    const origin = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const response = await fetch(origin + "/connections/google/gmail/process-one", {
      method: "POST", headers: { Authorization: "Bearer " + accessToken },
      cache: "no-store", signal: AbortSignal.timeout(58000),
    });
    if (!response.ok) {
      const status = [401, 409, 429, 503].includes(response.status) ? response.status : 502;
      const errors: Record<number, string> = {
        401: "Authentication required", 409: "Source changed; retry",
        429: "Extraction limit reached", 502: "Processing failed",
        503: "Processing temporarily unavailable",
      };
      return NextResponse.json({ error: errors[status] }, { status, headers: { "Cache-Control": "no-store" } });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Processing unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
