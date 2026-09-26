import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

const NO_STORE = { "Cache-Control": "no-store" };

function unavailable(status: number): NextResponse {
  if (status === 401) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401, headers: NO_STORE });
  }
  if (status === 422) {
    return NextResponse.json({ error: "Project name is invalid." }, { status: 422, headers: NO_STORE });
  }
  return NextResponse.json({ error: "Project service is unavailable." }, { status: 503, headers: NO_STORE });
}

async function callApi(path: string, init: RequestInit): Promise<NextResponse> {
  try {
    const url = new URL(path, requireServerEnv("FOCUSOS_API_URL"));
    const response = await fetch(url, {
      ...init,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return unavailable(response.status);
    return NextResponse.json(await response.json(), { headers: NO_STORE });
  } catch {
    return unavailable(503);
  }
}

export async function GET(): Promise<NextResponse> {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return unavailable(401);
  return callApi("/projects", {
    headers: { Authorization: "Bearer " + accessToken },
  });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const accessToken = await getServerAccessToken();
  if (!accessToken) return unavailable(401);

  const length = Number(request.headers.get("Content-Length") ?? 0);
  if (length > 4096) {
    return NextResponse.json({ error: "Project name is too large." }, { status: 413, headers: NO_STORE });
  }

  let body: unknown;
  try {
    const rawBody = await request.text();
    if (rawBody.length > 4096) {
      return NextResponse.json({ error: "Project name is too large." }, { status: 413, headers: NO_STORE });
    }
    body = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: "Project details must be valid JSON." }, { status: 400, headers: NO_STORE });
  }

  return callApi("/projects", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + accessToken,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}
