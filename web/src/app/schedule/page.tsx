import { getMe } from "@/server/api/me";
import { ScheduleBoard } from "./schedule-board";
export const dynamic = "force-dynamic";
export default async function SchedulePage() {
  const me = await getMe();
  return (
    <main className="agent-page">
      <header className="activity-hero">
        <nav className="activity-nav">
          <a href="/">Today</a>
          <a href="/tasks">Tasks</a>
        </nav>
        <span className="activity-eyebrow">FOCUSOS / SCHEDULE</span>
        <h1>Time reserved for your work</h1>
        <p>
          Follow saved blocks, manage cancellations, and plan the next session.
        </p>
      </header>
      {me.kind === "ok" ? (
        <ScheduleBoard />
      ) : (
        <p>Sign in from Today to view your schedule.</p>
      )}
    </main>
  );
}
