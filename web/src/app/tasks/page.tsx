import { getMe } from "@/server/api/me";
import { TaskWorkspace } from "./task-workspace";
export const dynamic = "force-dynamic";
export default async function TasksPage() {
  const me = await getMe();
  return (
    <main className="agent-page">
      <header className="activity-hero">
        <nav className="activity-nav">
          <a href="/">Today</a>
          <a href="/schedule">Schedule</a>
        </nav>
        <span className="activity-eyebrow">FOCUSOS / TASKS</span>
        <h1>Your task workspace</h1>
        <p>
          Keep active work, completed tasks, and archived ideas in one place.
        </p>
      </header>
      {me.kind === "ok" ? (
        <TaskWorkspace />
      ) : (
        <p>Sign in from Today to manage your tasks.</p>
      )}
    </main>
  );
}
