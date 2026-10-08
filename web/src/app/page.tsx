import { signInWithGoogle, signOut } from "./auth/actions";
import { getMe } from "@/server/api/me";
import { TaskBoard } from "./tasks/task-board";
import { WorkComposer } from "./work-composer";
import { GmailSyncPanel } from "./activity/gmail-sync-panel";
import { MemorySearch } from "./memories/memory-search";
import { Preferences } from "./settings/preferences";
import { ScheduleBoard } from "./schedule/schedule-board";

export const dynamic = "force-dynamic";
const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function clock(minutes: number) {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}
export default async function Home({ searchParams }: { searchParams: Promise<{ authError?: string; saved?: string; error?: string; source?: string }> }) {
  const [me, params] = await Promise.all([getMe(), searchParams]);
  const user = me.kind === "ok" ? me.data.user : me.kind === "unavailable" ? me.user : null;
  const profile = me.kind === "ok" ? me.data.profile : null;
  const timezone = profile?.timezone ?? "Asia/Jakarta";
  const now = new Date();
  const date = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: timezone }).format(now);
  const authError = params.authError === "callback" ? "Google sign-in did not complete. Please try again."
    : params.authError === "start" ? "Could not start Google sign-in." : params.authError === "logout" ? "Could not sign out. Please try again." : null;
  return <main className="home-page">
    <header className="app-header">
      <div className="app-header-inner">
        <a className="app-brand" href="/" aria-label="FocusOS home"><span className="brand-mark" aria-hidden="true">f.</span>FocusOS</a>
        {user && <nav aria-label="Main navigation"><a href="/#composer">Write</a><a href="/#tasks">Tasks</a><a href="/#schedule">Calendar</a><a href="/#memories">Memory</a></nav>}
        {user && <div className="header-actions"><GmailSyncPanel /><form action={signOut}><button className="secondary-button" type="submit">Sign out</button></form></div>}
      </div>
    </header>
    <div className="home-header">
      <div className="workspace-welcome"><time dateTime={now.toISOString()} className="workspace-date">{date}</time><h1>Your desk.</h1><p>A place for your work, your time, and the things you want to remember.</p></div>
      {user && <aside className="workspace-rhythm" aria-label="Your scheduling preferences">
        <span>YOUR WORKING WINDOW</span>
        {profile ? <><strong>{clock(profile.working_hours.start_minute)} <span aria-hidden="true">-</span> {clock(profile.working_hours.end_minute)}</strong><p>{profile.working_hours.days.map(day => dayNames[day - 1]).join(" / ")}</p><small>{timezone}</small></> : <p>Choose your working hours to start scheduling.</p>}
        <div><a href="/#preferences">Preferences</a><a href="/settings/connections">Google connection</a></div>
      </aside>}
    </div>
    {authError && <p role="alert">{authError}</p>}
    {user ? <>
      {me.kind === "unavailable" && <p role="alert">Your profile is temporarily unavailable. Refresh to try again.</p>}
      <WorkComposer />
      {me.kind === "ok" && <>
        <div id="tasks" className="workspace-tasks"><TaskBoard /></div>
        <div className="workspace-secondary">
          <details id="schedule" className="home-panel schedule-panel" open><summary><span>Scheduled work</span><small>Your Calendar</small></summary><div className="home-panel-body"><ScheduleBoard /></div></details>
          <section id="memories" className="home-memory"><div className="home-section-heading"><span className="section-eyebrow">SAVED KNOWLEDGE</span><h2>Search your memory</h2><p>Answers from the things you have saved.</p></div><MemorySearch /></section>
        </div>
        <Preferences profile={me.data.profile} saved={params.saved} error={params.error} />
      </>}
      <footer className="workspace-footer"><span>FocusOS / Personal workspace</span><a href="/#composer">Back to your desk</a></footer>
    </> : <section className="workspace-signin"><h2>Start with what is on your mind.</h2><p>Sign in to organize your tasks and make time for them.</p><form action={signInWithGoogle}><button type="submit">Continue with Google</button></form></section>}
  </main>;
}
