import { getMe } from "@/server/api/me";

export const dynamic = "force-dynamic";

const noStore = { "Cache-Control": "no-store" };

export async function GET() {
  const result = await getMe();
  if (result.kind === "unauthorized") {
    return Response.json(
      { error: { code: "unauthorized", message: "Authentication required" } },
      { status: 401, headers: noStore },
    );
  }
  if (result.kind === "unavailable") {
    return Response.json(
      { error: { code: "unavailable", message: "Profile unavailable" } },
      { status: 503, headers: noStore },
    );
  }
  return Response.json(result.data, { headers: noStore });
}
