import { getMe } from "@/server/api/me";
import { SourceReview } from "./source-review";

export const dynamic = "force-dynamic";

export default async function ActivityPage() {
  const me = await getMe();
  if (me.kind !== "ok") {
    return <main><h1>Extraction review</h1><p>Sign in to review your sources.</p><a href="/">Go to sign in</a></main>;
  }
  return (
    <main className="activity-page">
      <header>
        <a href="/">← Today</a>
        <h1>Extraction review</h1>
        <p>Paste one selected source, inspect the evidence, then decide what becomes a task.</p>
      </header>
      <SourceReview />
    </main>
  );
}
