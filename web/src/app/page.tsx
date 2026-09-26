import { signInWithGoogle, signOut } from "./auth/actions";
import { getServerUser } from "@/server/auth/session";

export const dynamic = "force-dynamic";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ authError?: string }>;
}) {
  const [user, params] = await Promise.all([getServerUser(), searchParams]);
  const authError =
    params.authError === "callback"
      ? "Google sign-in did not complete. Please try again."
      : params.authError === "start"
        ? "Could not start Google sign-in. Check the Supabase configuration."
        : params.authError === "logout"
          ? "Could not sign out. Please try again."
          : null;

  return (
    <main>
      <h1>FocusOS</h1>
      <p>Your personal AI productivity agent starts here.</p>
      {authError ? <p role="alert">{authError}</p> : null}
      {user ? (
        <>
          <p>Signed in{user.email ? ` as ${user.email}` : ""}.</p>
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
