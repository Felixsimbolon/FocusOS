import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { UUID_PATTERN, forward, relayError } from "@/server/forward";
type Context = { params: Promise<{ fileId: string }> };

async function relay(context: Context, path: (id: string) => string, method: "GET" | "POST", fallback: string) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { fileId } = await context.params;
  if (!UUID_PATTERN.test(fileId)) return NextResponse.json({ error: "Not found" }, { status: 404 });
  try {
    const response = await forward(token, path(fileId), method);
    if (!response.ok) return relayError(response, fallback);
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: fallback }, { status: 503 }); }
}

/** GET: a link that opens the file for a few minutes. */
export function GET(_: Request, context: Context) { return relay(context, id => `/files/${id}/link`, "GET", "This file cannot be opened right now."); }
/** DELETE: forget the file and remove its bytes. */
export function DELETE(_: Request, context: Context) { return relay(context, id => `/files/${id}/delete`, "POST", "Could not delete this file."); }
