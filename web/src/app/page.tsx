import { signInWithGoogle, signOut } from "./auth/actions";
import { getMe } from "@/server/api/me";
import { TaskBoard } from "./tasks/task-board";
import { CalendarAvailability } from "./calendar-availability";
import { MemorySearch } from "./memories/memory-search";
import { Preferences } from "./settings/preferences";
import { ScheduleBoard } from "./schedule/schedule-board";

export const dynamic = "force-dynamic";
export default async function Home({ searchParams }: { searchParams: Promise<{ authError?: string; saved?: string; error?: string }> }) {
  const [me, params] = await Promise.all([getMe(), searchParams]);
  const user = me.kind === "ok" ? me.data.user : me.kind === "unavailable" ? me.user : null;
  const authError = params.authError === "callback" ? "Google sign-in did not complete. Please try again."
    : params.authError === "start" ? "Could not start Google sign-in." : params.authError === "logout" ? "Could not sign out. Please try again." : null;
  return <main className="home-page">
    <header className="app-header">
      <a className="app-brand" href="/">FocusOS</a>
      {user && <nav aria-label="Main navigation"><a href="/" aria-current="page">Today</a><a href="/activity">Activity</a><a href="/agent">Plan</a><a href="/settings/connections">Google connection</a></nav>}
      {user && <form action={signOut}><button className="secondary-button" type="submit">Sign out</button></form>}
    </header>
    <div className="home-header"><span className="section-eyebrow">YOUR DAY, IN FOCUS</span><h1>Make room for what matters.</h1><p>Your work, knowledge, and time in one place.</p></div>
    {authError && <p role="alert">{authError}</p>}
    {user ? <>
      {me.kind === "unavailable" && <p role="alert">Your profile is temporarily unavailable. Refresh to try again.</p>}
      <div className="home-primary-actions"><a href="/activity#describe-work">Describe your work</a><a href="/agent">Plan my time</a></div>
      {me.kind === "ok" && <>
        <TaskBoard />
        <section id="memories" className="home-memory"><div className="home-section-heading"><h2>Search your memory</h2><p>Find an answer with its original source.</p></div><MemorySearch /></section>
        <CalendarAvailability />
        <details id="schedule" className="home-panel"><summary><span>Scheduled work</span><small>Your saved Calendar blocks</small></summary><div className="home-panel-body"><ScheduleBoard /></div></details>
        <Preferences profile={me.data.profile} saved={params.saved} error={params.error} />
      </>}
    </> : <form action={signInWithGoogle}><button type="submit">Continue with Google</button></form>}
  </main>;
}
