import { createClient } from "@/lib/supabase/server";
import { getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export const dynamic = "force-dynamic";

const noStore = { "Cache-Control": "no-store" };

export async function GET() {
  const user = await getServerUser();
  if (!user) {
    return Response.json({ error: "Authentication required" }, { status: 401, headers: noStore });
  }

  const supabase = await createClient();
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session) {
    return Response.json({ error: "Authentication required" }, { status: 401, headers: noStore });
  }

  try {
    const endpoint = new URL("/health/database", requireServerEnv("FOCUSOS_API_URL"));
    const response = await fetch(endpoint, {
      headers: { Authorization: `Bearer ${data.session.access_token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });

    if (response.status === 200) {
      return Response.json({ status: "ok" }, { headers: noStore });
    }
  } catch {
    // Do not expose backend details or the access token to the browser.
  }

  return Response.json({ error: "Database check unavailable" }, { status: 503, headers: noStore });
}
