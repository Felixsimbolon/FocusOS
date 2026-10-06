import { signInWithGoogle, signOut } from "./auth/actions";
import { getMe } from "@/server/api/me";
import { TaskBoard } from "./tasks/task-board";
import { CalendarAvailability } from "./calendar-availability";

export const dynamic = "force-dynamic";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ authError?: string }>;
}) {
  const [me, params] = await Promise.all([getMe(), searchParams]);
  const authError =
    params.authError === "callback"
      ? "Google sign-in did not complete. Please try again."
      : params.authError === "start"
        ? "Could not start Google sign-in. Check the Supabase configuration."
        : params.authError === "logout"
          ? "Could not sign out. Please try again."
          : null;

  const user = me.kind === "ok" ? me.data.user : me.kind === "unavailable" ? me.user : null;

  return (
    <main className={user ? "home-page" : undefined}>
      <header className="home-header">
        <span className="section-eyebrow">FOCUSOS / TODAY</span>
        <h1>Your day, in focus.</h1>
        <p>A calmer place for your tasks, deadlines, and time to do the work.</p>
      </header>
      {authError ? <p role="alert">{authError}</p> : null}
      {user ? (
        <>
          <p className="home-account">Signed in{user.email ? ` as ${user.email}` : ""}</p>
          {me.kind === "unavailable" ? (
            <p role="alert">Your profile is temporarily unavailable.</p>
          ) : me.kind === "ok" && me.data.profile ? (
            <p>
              Scheduling timezone: {me.data.profile.timezone}. Working days:{" "}
              {me.data.profile.working_hours.days.join(", ")}.
            </p>
          ) : (
            <p>Set your scheduling preferences to get started.</p>
          )}
          <nav className="home-links" aria-label="FocusOS tools">
            <a href="/tasks"><strong>Task workspace</strong><span>Edit, complete, or archive your work</span></a>
            <a href="/schedule"><strong>Schedule</strong><span>Manage saved focus blocks</span></a>
            <a href="/system"><strong>System</strong><span>Jobs, diagnostics, and data export</span></a>
            <a href="/agent"><strong>Planning agent</strong><span>Turn your tasks into a plan</span></a>
            <a href="/activity"><strong>Activity and sources</strong><span>Organize selected email and notes</span></a>
            <a href="/memories"><strong>Search memories</strong><span>Find grounded facts again</span></a>
            <a href="/settings"><strong>Preferences</strong><span>Set your time and connections</span></a>
          </nav>
          {me.kind === "ok" ? <><TaskBoard /><CalendarAvailability /></> : null}
          <form action={signOut} className="home-signout">
            <button type="submit">Sign out</button>
          </form>
        </>
      ) : (
        <form action={signInWithGoogle}>
          <button type="submit">Continue with Google</button>
        </form>
      )}
    </main>
  );
}
