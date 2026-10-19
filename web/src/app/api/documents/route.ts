import { after, NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { runBackgroundJob } from "@/server/jobs";
import { FILE_KINDS, MAX_FILE_BYTES, fileType } from "@/lib/files";
export const maxDuration = 120;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** One attached file (PDF, image, Word or text): the API transcribes it and captures tasks and notes from the text. */
export async function POST(request: NextRequest) {
  const token = await getServerAccessToken();
  if (!token) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  let form: FormData;
  try { form = await request.formData(); } catch { return NextResponse.json({ error: "Attach one file." }, { status: 400 }); }
  const file = form.get("file"), key = form.get("request_key");
  if (!(file instanceof File) || typeof key !== "string" || !UUID.test(key) || [...form.keys()].some(name => !["file", "request_key"].includes(name)))
    return NextResponse.json({ error: "Attach one file." }, { status: 400 });
  const type = fileType(file);
  if (!type) return NextResponse.json({ error: `Attach a ${FILE_KINDS} file.` }, { status: 415 });
  if (file.size > MAX_FILE_BYTES) return NextResponse.json({ error: "Attach a file of at most 3 MB." }, { status: 413 });
  const data = Buffer.from(await file.arrayBuffer()).toString("base64");
  try {
    const response = await fetch(requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "") + "/documents", {
      method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: JSON.stringify({ request_key: key, filename: file.name.slice(0, 120) || "document", mime_type: type, data }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(90_000),
    });
    if (!response.ok) {
      const status = [401, 409, 422, 429].includes(response.status) ? response.status : 503;
      // 422 carries the API's fixed explanation (unreadable file, no text); never provider text.
      const detail = status === 422 ? await response.json().then(body => body?.detail, () => null) : null;
      return NextResponse.json({ error: status === 401 ? "Sign in again to continue." : typeof detail === "string" && detail.length <= 200 ? detail
        : status === 429 ? "Processing limit reached. Wait before attaching another file." : "Could not read this document right now. Try again in a moment." }, { status });
    }
    const result = await response.json();
    after(async () => { try { await runBackgroundJob(token, result.background_job); } catch { /* The queue retains progress. */ } });
    return NextResponse.json(result, { status: 202, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Could not read this document right now. Try again in a moment." }, { status: 503 }); }
}
