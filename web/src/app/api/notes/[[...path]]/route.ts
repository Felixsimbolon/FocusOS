import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { runBackgroundJob } from "@/server/jobs";
import { UUID_PATTERN, forward, jsonBody, relayError } from "@/server/forward";
export const maxDuration = 120;
type Context = { params: Promise<{ path?: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const path = (await context.params).path ?? [];
  const project = request.nextUrl.searchParams.get("project_id");
  if (path.length > 1 || (path.length === 1 && !UUID_PATTERN.test(path[0])) || (project && !UUID_PATTERN.test(project)))
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  try {
    const response = await forward(token, path.length ? `/notes/${path[0]}` : `/notes${project ? `?project_id=${project}` : ""}`, "GET");
    if (!response.ok) return relayError(response, "Notes are unavailable right now.");
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Notes are unavailable right now." }, { status: 503 }); }
}

/** Save (POST /api/notes/<id>), delete (<id>/delete), or turn into tasks (<id>/capture). */
export async function POST(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const path = (await context.params).path ?? [];
  if (!path.length || !UUID_PATTERN.test(path[0]) || path.length > 2 || (path[1] && !["delete", "capture"].includes(path[1])))
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  let body: string | undefined;
  if (!path[1]) {
    const value = await jsonBody(request, ["project_id", "title", "body", "expected_version"]);
    if (!value || typeof value.title !== "string" || !value.title.trim() || value.title.length > 200 || typeof value.body !== "string"
      || value.body.length > 50_000 || !Number.isInteger(value.expected_version))
      return NextResponse.json({ error: "A note needs a title, and at most 50,000 characters." }, { status: 400 });
    if (typeof value.project_id !== "string" || !UUID_PATTERN.test(value.project_id))
      return NextResponse.json({ error: "Choose a project for this note." }, { status: 400 });
    body = JSON.stringify({ project_id: value.project_id, title: value.title, body: value.body, expected_version: value.expected_version });
  } else if (path[1] === "capture") {
    const value = await jsonBody(request, ["request_key"]);
    if (!value || typeof value.request_key !== "string" || !UUID_PATTERN.test(value.request_key)) return NextResponse.json({ error: "Invalid request." }, { status: 400 });
    body = JSON.stringify({ request_key: value.request_key });
  }
  try {
    const response = await forward(token, `/notes/${path.join("/")}`, "POST", body);
    if (!response.ok) return relayError(response, "Could not save this note. Your text is still in the editor; try again.");
    const result = await response.json();
    if (path[1] === "capture" && result.background_job)
      after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* The queue retains progress. */ } });
    return NextResponse.json(result, { status: path[1] === "capture" ? 202 : 200, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Could not save this note. Your text is still in the editor; try again." }, { status: 503 }); }
}
