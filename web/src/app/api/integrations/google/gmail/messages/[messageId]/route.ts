import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ messageId: string }> },
) {
  const accessToken = await getServerAccessToken();
  if (!accessToken) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  const { messageId } = await params;
  try {
    const apiUrl = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
    const response = await fetch(
      apiUrl + "/connections/google/gmail/messages/" + encodeURIComponent(messageId),
      {
        headers: { Authorization: "Bearer " + accessToken },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      const status = response.status === 409 ? 409 : response.status === 401 ? 401 : 502;
      return NextResponse.json(
        { error: status === 409 ? "Google reconnection required" : "Gmail probe failed" },
        { status, headers: { "Cache-Control": "no-store" } },
      );
    }
    const result = await response.json();
    return NextResponse.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json(
      { error: "Gmail probe unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
