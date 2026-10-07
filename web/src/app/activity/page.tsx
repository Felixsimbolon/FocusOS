import { getMe } from "@/server/api/me";
import { SourceReview } from "./source-review";
import { GmailSyncPanel } from "./gmail-sync-panel";

export const dynamic = "force-dynamic";

export default async function ActivityPage() {
  const me = await getMe();
  if (me.kind !== "ok") {
    return <main><h1>Activity</h1><p>Sign in to organize your sources.</p><a href="/">Go to sign in</a></main>;
  }
  return (
    <main className="activity-page">
      <header className="activity-hero">
        <nav className="activity-nav"><a href="/">Today</a><span>FOCUSOS / ACTIVITY</span></nav>
        <span className="activity-eyebrow">YOUR SECOND BRAIN, IN MOTION</span>
        <h1>Turn inputs into progress.</h1>
        <p>Sync selected email or describe your work. Tasks and memories are saved automatically.</p>
      </header>
      <GmailSyncPanel />
      <SourceReview />
    </main>
  );
}
