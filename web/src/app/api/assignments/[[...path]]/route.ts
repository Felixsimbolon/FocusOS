import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { runBackgroundJob } from "@/server/jobs";
import { UUID_PATTERN, forward, jsonBody, relayError } from "@/server/forward";
export const maxDuration = 120;
type Context = { params: Promise<{ path?: string[] }> };
const FILE_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 3_000_000;
const LEVELS = ["understood", "partly", "not"];

export async function GET(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const path = (await context.params).path ?? [];
  const project = request.nextUrl.searchParams.get("project_id");
  if (path.length > 1 || (path.length === 1 && !UUID_PATTERN.test(path[0])) || (project && !UUID_PATTERN.test(project)))
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  try {
    const response = await forward(token, path.length ? `/assignments/${path[0]}` : `/assignments${project ? `?project_id=${project}` : ""}`, "GET");
    if (!response.ok) return relayError(response, "Assignments are unavailable right now.");
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Assignments are unavailable right now." }, { status: 503 }); }
}

/** Upload a brief (multipart), then analyze, answer understanding questions, and plan (runs the booking job). */
export async function POST(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const path = (await context.params).path ?? [];
  let target: string, body: string | undefined, timeout = 60_000;
  if (!path.length) {
    let form: FormData;
    try { form = await request.formData(); } catch { return NextResponse.json({ error: "Attach one file." }, { status: 400 }); }
    const file = form.get("file"), key = form.get("request_key");
    if (!(file instanceof File) || typeof key !== "string" || !UUID_PATTERN.test(key) || [...form.keys()].some(name => !["file", "request_key"].includes(name)))
      return NextResponse.json({ error: "Attach one file." }, { status: 400 });
    if (!FILE_TYPES.includes(file.type)) return NextResponse.json({ error: "Attach a PDF, PNG, JPEG or WebP file." }, { status: 415 });
    if (file.size > MAX_BYTES) return NextResponse.json({ error: "Attach a file of at most 3 MB." }, { status: 413 });
    target = "/assignments"; timeout = 90_000;
    body = JSON.stringify({ request_key: key, filename: file.name.slice(0, 120) || "assignment", mime_type: file.type,
      data: Buffer.from(await file.arrayBuffer()).toString("base64") });
  } else {
    if (path.length !== 2 || !UUID_PATTERN.test(path[0]) || !["analyze", "understanding", "plan"].includes(path[1]))
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    target = `/assignments/${path[0]}/${path[1]}`;
    if (path[1] === "understanding") {
      const value = await jsonBody(request, ["expected_version", "answers"]);
      const answers = value?.answers as Record<string, unknown> | undefined;
      if (!value || !Number.isInteger(value.expected_version) || !answers || typeof answers !== "object"
        || Object.entries(answers).some(([index, level]) => !/^[0-9]$/.test(index) || !LEVELS.includes(level as string)))
        return NextResponse.json({ error: "Invalid answers." }, { status: 400 });
      body = JSON.stringify({ expected_version: value.expected_version, answers });
    } else if (path[1] === "plan") {
      const value = await jsonBody(request, ["expected_version", "request_key", "project_id", "project_name"]);
      if (!value || !Number.isInteger(value.expected_version) || typeof value.request_key !== "string" || !UUID_PATTERN.test(value.request_key)
        || (value.project_id !== undefined && (typeof value.project_id !== "string" || !UUID_PATTERN.test(value.project_id)))
        || (value.project_name !== undefined && (typeof value.project_name !== "string" || !value.project_name.trim() || value.project_name.length > 100)))
        return NextResponse.json({ error: "Invalid plan request." }, { status: 400 });
      body = JSON.stringify(value);
    } else { timeout = 90_000; }
  }
  try {
    const response = await forward(token, target, "POST", body, timeout);
    if (!response.ok) return relayError(response, "Could not finish this step right now. Try again in a moment.");
    const result = await response.json();
    if (path[1] === "plan" && result.background_job)
      after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* The queue retains progress. */ } });
    return NextResponse.json(result, { status: path[1] === "plan" ? 202 : 200, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Could not finish this step right now. Try again in a moment." }, { status: 503 }); }
}
