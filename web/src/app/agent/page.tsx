import { getMe } from "@/server/api/me";
import { AgentConsole } from "./agent-console";

export const dynamic = "force-dynamic";

export default async function AgentPage() {
  const me = await getMe();
  if (me.kind !== "ok") return <main><h1>Planning agent</h1><p>Sign in to create a plan.</p><a href="/">Go to sign in</a></main>;
  return <main className="agent-page"><a href="/">← Today</a><h1>Planning agent</h1>
    <p>Describe what you want to plan. FocusOS will read your tasks and availability, then add valid work blocks to your Google Calendar automatically.</p>
    <p>To look up a saved fact without planning a calendar block, use <a href="/#memories">Search memories</a>.</p>
    <AgentConsole /><p><a href="https://github.com/Felixsimbolon/FocusOS/blob/main/docs/evaluation.md">Evaluation report and limitations</a></p></main>;
}
