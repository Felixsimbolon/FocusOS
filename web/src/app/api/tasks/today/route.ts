import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export async function GET(): Promise<NextResponse> {
  const accessToken = await getServerAccessToken();
  if (!accessToken) {
    return NextResponse.json(
      { error: "Authentication required" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const url = new URL("/tasks/today", requireServerEnv("FOCUSOS_API_URL"));
    const response = await fetch(url, {
      headers: { Authorization: "Bearer " + accessToken },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      return NextResponse.json(
        { error: response.status === 401 ? "Authentication required" : "Today tasks are unavailable." },
        {
          status: response.status === 401 ? 401 : 503,
          headers: { "Cache-Control": "no-store" },
        },
      );
    }
    return NextResponse.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "Today tasks are unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
