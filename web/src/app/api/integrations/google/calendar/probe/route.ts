import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export async function GET() {
  const accessToken = await getServerAccessToken();
  if (!accessToken) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  try {
    const apiUrl = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const response = await fetch(apiUrl + "/connections/google/calendar/probe", {
      headers: { Authorization: "Bearer " + accessToken },
      cache: "no-store",
    });
    if (!response.ok) {
      const status = response.status === 409 ? 409 : response.status === 401 ? 401 : 502;
      return NextResponse.json(
        { error: status === 409 ? "Google reconnection required" : "Calendar probe failed" },
        { status, headers: { "Cache-Control": "no-store" } },
      );
    }
    return NextResponse.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "Calendar probe unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
