import { getMe } from "@/server/api/me";
import { SystemConsole } from "./system-console";
export const dynamic = "force-dynamic";
export default async function SystemPage() {
  const me = await getMe();
  return (
    <main className="agent-page">
      <header className="activity-hero">
        <nav className="activity-nav">
          <a href="/">Today</a>
          <a href="/settings/connections">Connections</a>
        </nav>
        <span className="activity-eyebrow">FOCUSOS / SYSTEM</span>
        <h1>Your system, at a glance</h1>
        <p>
          Follow processing, revisit plans, check setup, and keep a copy of your
          data.
        </p>
      </header>
      {me.kind === "ok" ? (
        <SystemConsole />
      ) : (
        <p>Sign in from Today to view your system.</p>
      )}
    </main>
  );
}
