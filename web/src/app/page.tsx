import { signInWithGoogle, signOut } from "./auth/actions";
import { getMe } from "@/server/api/me";
import { TaskBoard } from "./tasks/task-board";

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
        <h1>FocusOS</h1>
        <p>Your personal AI productivity agent starts here.</p>
      </header>
      {authError ? <p role="alert">{authError}</p> : null}
      {user ? (
        <>
          <p>Signed in{user.email ? ` as ${user.email}` : ""}.</p>
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
          {me.kind === "ok" ? <TaskBoard /> : null}
          <a href="/settings">Scheduling preferences</a>
          <form action={signOut}>
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
