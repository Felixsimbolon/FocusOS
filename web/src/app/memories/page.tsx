import { getMe } from "@/server/api/me";
import { MemorySearch } from "./memory-search";

export const dynamic = "force-dynamic";

export default async function MemoriesPage() {
  const me = await getMe();
  if (me.kind !== "ok") {
    return <main className="agent-page"><h1>Search memories</h1><p>Sign in to search your saved facts.</p><a href="/">Go to sign in</a></main>;
  }
  return <main className="agent-page">
    <a href="/">Back to Today</a>
    <h1>Search memories</h1>
    <p>Find facts you confirmed from a source. Results include the exact quote used as evidence.</p>
    <MemorySearch />
  </main>;
}
