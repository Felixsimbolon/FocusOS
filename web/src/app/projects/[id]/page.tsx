import { notFound, redirect } from "next/navigation";
import { getServerAccessToken, getServerUser } from "@/server/auth/session";
import { forward, UUID_PATTERN } from "@/server/forward";
import { readProfile } from "@/server/api/profile";
import { Topbar } from "../../topbar";
import { ProjectView, type ProjectDetail } from "../project-view";

export const dynamic = "force-dynamic";

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID_PATTERN.test(id)) notFound();
  const [user, token, profile] = await Promise.all([getServerUser(), getServerAccessToken(), readProfile()]);
  if (!user || !token) redirect("/");
  let detail: ProjectDetail | null = null, status = 0;
  try {
    const response = await forward(token, `/projects/${id}/detail`, "GET", undefined, 8_000);
    status = response.status;
    if (response.ok) detail = await response.json() as ProjectDetail;
  } catch { /* The page loads the project itself when the first read fails. */ }
  if (status === 404) notFound();
  const timezone = profile.kind === "ok" && profile.profile ? profile.profile.timezone : "Asia/Jakarta";
  return <main className="home project-page">
    <Topbar signedIn />
    <ProjectView id={id} initial={detail} timezone={timezone} />
  </main>;
}
