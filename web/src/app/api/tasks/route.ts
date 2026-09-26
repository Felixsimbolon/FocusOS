import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NO_STORE = { "Cache-Control": "no-store" };

function failure(status: number): NextResponse {
  const safeStatus =
    status === 401 || status === 409 || status === 422
      ? status
      : status >= 500
        ? 503
        : 502;
  const error =
    safeStatus === 401
      ? "Authentication required"
      : safeStatus === 409
        ? "This task request key was already used for different details."
        : safeStatus === 422
          ? "Task details are invalid."
          : "Task service is unavailable.";
  return NextResponse.json({ error }, { status: safeStatus, headers: NO_STORE });
}

async function proxy(path: string, init: RequestInit): Promise<NextResponse> {
  try {
    const url = new URL(path, requireServerEnv("FOCUSOS_API_URL"));
    const response = await fetch(url, {
      ...init,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return failure(response.status);
    return NextResponse.json(await response.json(), { headers: NO_STORE });
  } catch {
    return failure(503);
  }
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return failure(401);

  const params = request.nextUrl.searchParams;
  const status = params.get("status");
  const limit = params.get("limit");
  if (status && !["open", "done", "archived"].includes(status)) {
    return NextResponse.json({ error: "Task status is invalid." }, { status: 400, headers: NO_STORE });
  }
  if (limit && (!/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 100)) {
    return NextResponse.json({ error: "Task limit is invalid." }, { status: 400, headers: NO_STORE });
  }

  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (limit) query.set("limit", limit);
  return proxy("/tasks" + (query.size ? "?" + query.toString() : ""), {
    headers: { Authorization: "Bearer " + accessToken },
  });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return failure(401);

  const requestId = request.headers.get("Idempotency-Key");
  if (!requestId || !UUID_PATTERN.test(requestId)) {
    return NextResponse.json(
      { error: "A valid task request key is required." },
      { status: 400, headers: NO_STORE },
    );
  }

  const length = Number(request.headers.get("Content-Length") ?? 0);
  if (length > 16_384) {
    return NextResponse.json({ error: "Task details are too large." }, { status: 413, headers: NO_STORE });
  }

  let body: unknown;
  try {
    const rawBody = await request.text();
    if (rawBody.length > 16_384) {
      return NextResponse.json({ error: "Task details are too large." }, { status: 413, headers: NO_STORE });
    }
    body = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: "Task details must be valid JSON." }, { status: 400, headers: NO_STORE });
  }

  return proxy("/tasks", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + accessToken,
      "Content-Type": "application/json",
      "Idempotency-Key": requestId,
    },
    body: JSON.stringify(body),
  });
}
