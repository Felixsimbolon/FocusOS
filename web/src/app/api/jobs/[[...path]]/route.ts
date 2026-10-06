import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { runBackgroundJob, type BackgroundJob } from "@/server/jobs";
export const maxDuration = 240;
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Context = { params: Promise<{ path?: string[] }> };
async function proxy(
  request: NextRequest,
  context: Context,
  method: "GET" | "POST",
) {
  const token = await getServerAccessToken();
  if (!token)
    return NextResponse.json(
      { error: "Authentication required" },
      { status: 401 },
    );
  const path = (await context.params).path || [];
  const valid =
    method === "GET"
      ? path.length === 0 || (path.length === 1 && UUID.test(path[0]))
      : path.length === 0 ||
        (path.length === 2 &&
          UUID.test(path[0]) &&
          ["resume", "cancel"].includes(path[1]));
  if (!valid)
    return NextResponse.json({ error: "Job route not found" }, { status: 404 });
  const isResume = path[1] === "resume";
  let body: string | undefined;
  if (method === "POST" && !path.length) {
    body = await request.text();
    if (body.length > 1024)
      return NextResponse.json(
        { error: "Job request too large" },
        { status: 413 },
      );
    try {
      JSON.parse(body);
    } catch {
      return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
    }
  }
  try {
    const suffix = isResume ? path[0] : path.join("/");
    const response = await fetch(
      requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") +
        "/jobs" +
        (suffix ? "/" + suffix : ""),
      {
        method: isResume ? "GET" : method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(15_000),
      },
    );
    if (!response.ok) {
      const status = [401, 404, 409, 422, 429].includes(response.status)
        ? response.status
        : 503;
      return NextResponse.json(
        {
          error:
            status === 401
              ? "Sign in again to start processing."
              : status === 429
                ? "Processing limit reached. Wait before submitting again."
                : "Background processing unavailable. Check System diagnostics.",
        },
        { status },
      );
    }
    const result = await response.json();
    if (method === "POST" && (!path.length || isResume))
      after(async () => {
        try {
          await runBackgroundJob(token, result as BackgroundJob);
        } catch {
          /* Queue status remains durable; no secrets are logged. */
        }
      });
    return NextResponse.json(result, {
      status: !path.length && method === "POST" ? 202 : 200,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "Background processing unavailable. Check System diagnostics." },
      { status: 503 },
    );
  }
}
export async function GET(request: NextRequest, context: Context) {
  return proxy(request, context, "GET");
}
export async function POST(request: NextRequest, context: Context) {
  return proxy(request, context, "POST");
}
