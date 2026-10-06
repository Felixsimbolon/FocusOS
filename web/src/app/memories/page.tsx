import { getMe } from "@/server/api/me";
import { MemoryLibrary } from "./memory-library";
import { MemorySearch } from "./memory-search";

export const dynamic = "force-dynamic";

export default async function MemoriesPage() {
  const me = await getMe();
  return (
    <main className="agent-page">
      <header className="activity-hero">
        <nav className="activity-nav" aria-label="Page navigation">
          <a href="/">&larr; Today</a>
          <span>FOCUSOS / MEMORY</span>
        </nav>
        <span className="activity-eyebrow">YOUR KNOWLEDGE, WITH CONTEXT</span>
        <h1>Search memories</h1>
        <p>Ask about saved facts and manually added tasks. Each answer links back to its evidence.</p>
      </header>
      {me.kind === "ok" ? (
        <><MemorySearch /><MemoryLibrary /></>
      ) : (
        <section className="review-panel">
          <p>Sign in to search your saved facts.</p>
          <a href="/">Go to sign in</a>
        </section>
      )}
    </main>
  );
}
