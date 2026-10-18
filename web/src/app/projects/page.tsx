import { redirect } from "next/navigation";
import { getServerAccessToken, getServerUser } from "@/server/auth/session";
import { forward } from "@/server/forward";
import { Topbar } from "../topbar";
import { ProjectsIndex } from "./projects-index";
import type { ProjectSummary } from "./projects-panel";

export const dynamic = "force-dynamic";

export default async function ProjectsPage() {
  const [user, token] = await Promise.all([getServerUser(), getServerAccessToken()]);
  if (!user || !token) redirect("/");
  let projects: ProjectSummary[] | null = null;
  try {
    const response = await forward(token, "/projects/overview", "GET", undefined, 8_000);
    if (response.ok) { const result = await response.json(); projects = Array.isArray(result) ? result : null; }
  } catch { /* The list loads in the browser when the first read fails. */ }
  return <main className="home projects-page">
    <Topbar signedIn />
    <ProjectsIndex initial={projects} />
  </main>;
}
