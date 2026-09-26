import { getMe } from "@/server/api/me";
import { AgentConsole } from "./agent-console";

export const dynamic = "force-dynamic";

export default async function AgentPage() {
  const me = await getMe();
  if (me.kind !== "ok") return <main><h1>Planning agent</h1><p>Sign in to create a plan.</p><a href="/">Go to sign in</a></main>;
  return <main className="agent-page"><a href="/">← Today</a><h1>Planning agent</h1>
    <p>Describe what you want to plan. FocusOS will read your tasks and availability, then show a proposal for review.</p>
    <AgentConsole /></main>;
}
