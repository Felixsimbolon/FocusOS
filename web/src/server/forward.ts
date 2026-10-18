import "server-only";
import { NextResponse } from "next/server";
import { requireServerEnv } from "./env";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** One call to the FocusOS API as the signed-in user. */
export function forward(token: string, path: string, method: "GET" | "POST", body?: string, timeoutMs = 45_000) {
  return fetch(requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") + path, {
    method, headers: { Authorization: "Bearer " + token, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(timeoutMs),
  });
}

/** Pass the API's own short explanation for 404/409/422/429; never provider or database text otherwise. */
export async function relayError(response: Response, fallback: string) {
  const status = [401, 404, 409, 422, 429].includes(response.status) ? response.status : 503;
  const detail = status === 401 ? null : await response.json().then(body => body?.detail, () => null);
  return NextResponse.json({ error: status === 401 ? "Sign in again to continue." : typeof detail === "string" && detail.length <= 200 ? detail : fallback }, { status });
}

/** Read a small JSON body, allowing only the listed keys. */
export async function jsonBody(request: Request, keys: string[], maxLength = 60_000): Promise<Record<string, unknown> | null> {
  const raw = await request.text();
  if (raw.length > maxLength) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !keys.includes(key))) return null;
    return value as Record<string, unknown>;
  } catch { return null; }
}
