import { NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { UUID_PATTERN, forward, relayError } from "@/server/forward";
type Context = { params: Promise<{ projectId: string }> };

/** GET /api/projects/overview: every project with counts; GET /api/projects/<id>: one project's tasks, notes, assignments, blocks. */
export async function GET(_: Request, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { projectId } = await context.params;
  if (projectId !== "overview" && !UUID_PATTERN.test(projectId)) return NextResponse.json({ error: "Not found" }, { status: 404 });
  try {
    const response = await forward(token, projectId === "overview" ? "/projects/overview" : `/projects/${projectId}/detail`, "GET");
    if (!response.ok) return relayError(response, "Projects are unavailable right now.");
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Projects are unavailable right now." }, { status: 503 }); }
}
