import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export async function DELETE() {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  try {
    const response = await fetch(new URL("/connections/google", requireServerEnv("FOCUSOS_API_URL")), {
      method: "DELETE", headers: { Authorization: "Bearer " + token }, cache: "no-store",
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) return NextResponse.json({ error: "Google disconnect unavailable" },
      { status: response.status === 401 ? 401 : 503 });
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Google disconnect unavailable" }, { status: 503 });
  }
}
