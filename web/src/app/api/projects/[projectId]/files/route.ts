import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { UUID_PATTERN, forward, relayError } from "@/server/forward";
import { FILE_TYPES, MAX_FILE_BYTES } from "@/lib/files";
export const maxDuration = 60;
type Context = { params: Promise<{ projectId: string }> };

/** POST (multipart: file, id): keep one PDF or photo with the project. */
export async function POST(request: NextRequest, context: Context) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const { projectId } = await context.params;
  if (!UUID_PATTERN.test(projectId)) return NextResponse.json({ error: "Not found" }, { status: 404 });
  let form: FormData;
  try { form = await request.formData(); } catch { return NextResponse.json({ error: "Attach one file." }, { status: 400 }); }
  const file = form.get("file"), id = form.get("id");
  if (!(file instanceof File) || typeof id !== "string" || !UUID_PATTERN.test(id) || [...form.keys()].some(name => !["file", "id"].includes(name)))
    return NextResponse.json({ error: "Attach one file." }, { status: 400 });
  if (!FILE_TYPES.includes(file.type)) return NextResponse.json({ error: "Attach a PDF, PNG, JPEG or WebP file." }, { status: 415 });
  if (file.size > MAX_FILE_BYTES) return NextResponse.json({ error: "Attach a file of at most 3 MB." }, { status: 413 });
  const data = Buffer.from(await file.arrayBuffer()).toString("base64");
  try {
    const response = await forward(token, `/projects/${projectId}/files`, "POST",
      JSON.stringify({ id, filename: file.name.slice(0, 120) || "file", mime_type: file.type, data }), 50_000);
    if (!response.ok) return relayError(response, "Could not keep this file right now. Try again in a moment.");
    return NextResponse.json(await response.json(), { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Could not keep this file right now. Try again in a moment." }, { status: 503 }); }
}
