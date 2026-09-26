import { getMe } from "@/server/api/me";
import { AgentConsole } from "../agent-console";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const me = await getMe();
  if (me.kind !== "ok") return <main><h1>Agent run</h1><p>Sign in to inspect this run.</p><a href="/">Go to sign in</a></main>;
  const { runId } = await params;
  return <main className="agent-page"><a href="/agent">← Planning agent</a><h1>Agent run</h1>
    <AgentConsole initialRunId={runId} /></main>;
}
