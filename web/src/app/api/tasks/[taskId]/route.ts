import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type RouteContext = { params: Promise<{ taskId: string }> };

function responseError(status: number): NextResponse {
  const safeStatus = status === 401 || status === 404 || status === 409 || status === 422
    ? status
    : 503;
  const error =
    safeStatus === 401
      ? "Authentication required"
      : safeStatus === 404
        ? "Task or project not found."
        : safeStatus === 409
          ? "Task changed since it was loaded. The latest task list has been reloaded."
          : safeStatus === 422
            ? "Task changes are invalid."
            : "Task service is unavailable.";
  return NextResponse.json({ error }, { status: safeStatus, headers: { "Cache-Control": "no-store" } });
}

export async function PATCH(
  request: NextRequest,
  context: RouteContext,
): Promise<NextResponse> {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return responseError(401);

  const { taskId } = await context.params;
  if (!UUID_PATTERN.test(taskId)) {
    return NextResponse.json(
      { error: "Task ID is invalid." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  const length = Number(request.headers.get("Content-Length") ?? 0);
  if (length > 16_384) {
    return NextResponse.json(
      { error: "Task changes are too large." },
      { status: 413, headers: { "Cache-Control": "no-store" } },
    );
  }

  let body: unknown;
  try {
    const rawBody = await request.text();
    if (rawBody.length > 16_384) {
      return NextResponse.json(
        { error: "Task changes are too large." },
        { status: 413, headers: { "Cache-Control": "no-store" } },
      );
    }
    body = JSON.parse(rawBody);
  } catch {
    return NextResponse.json(
      { error: "Task changes must be valid JSON." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const url = new URL("/tasks/" + encodeURIComponent(taskId), requireServerEnv("FOCUSOS_API_URL"));
    const response = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: "Bearer " + accessToken,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return responseError(response.status);
    return NextResponse.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return responseError(503);
  }
}
