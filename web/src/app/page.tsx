import { signInWithGoogle, signOut } from "./auth/actions";
import { getMe } from "@/server/api/me";
import { TaskBoard } from "./tasks/task-board";
import { WorkComposer } from "./work-composer";
import { GmailSyncPanel } from "./activity/gmail-sync-panel";
import { Preferences } from "./settings/preferences";
import { ScheduleBoard } from "./schedule/schedule-board";
import { UsagePanel } from "./usage/usage-panel";
import { FocusHud } from "./hud/focus-hud";
import { CheckInPanel } from "./check-ins/check-in-panel";
import { Conflicts } from "./schedule/conflicts";
import { MonthCalendar } from "./schedule/month-calendar";
import { ThemeToggle } from "./theme-toggle";
import { TriagePanel } from "./activity/triage-panel";
import { GraphPanel } from "./knowledge/graph-panel";
import { ReviewPanel } from "./review/review-panel";
import { Ridges } from "./art/ridges";
import { Sunrise } from "./art/spots";

export const dynamic = "force-dynamic";

function Brand() {
  return <a className="brand" href="/" aria-label="FocusOS home">
    <svg viewBox="0 0 32 20" aria-hidden="true"><path d="M2 18 H30" /><path d="M7 18 A9 9 0 0 1 25 18" /><circle cx="16" cy="11" r="3.2" /></svg>
    FocusOS
  </a>;
}

export default async function Home({ searchParams }: { searchParams: Promise<{ authError?: string; saved?: string; error?: string; source?: string }> }) {
  const [me, params] = await Promise.all([getMe(), searchParams]);
  const user = me.kind === "ok" ? me.data.user : me.kind === "unavailable" ? me.user : null;
  const profile = me.kind === "ok" ? me.data.profile : null;
  const name = me.kind === "ok" ? me.displayName : me.kind === "unavailable" ? me.user.name : undefined;
  const authError = params.authError === "callback" ? "Google sign-in did not complete. Try again."
    : params.authError === "start" ? "Could not start Google sign-in. Try again." : params.authError === "logout" ? "Could not sign out. Try again." : null;
  return <main className="home">
    <header className="topbar">
      <Brand />
      {!user && <div className="topbar-actions"><ThemeToggle /></div>}
      {user && <nav aria-label="Main navigation"><a href="/#composer">Write</a><a href="/#tasks">Today</a><a href="/#schedule">Calendar</a><a href="/#review">Review</a></nav>}
      {user && <div className="topbar-actions"><ThemeToggle /><GmailSyncPanel /><form action={signOut}><button className="quiet" type="submit">Sign out</button></form></div>}
    </header>
    {authError && <p role="alert" className="page-alert">{authError}</p>}
    {user ? <>
      {profile ? <FocusHud timezone={profile.timezone} hours={profile.working_hours} name={name} />
        : <section className="horizon horizon-setup" aria-label="Get started">
          <svg className="horizon-art" viewBox="0 0 1440 420" preserveAspectRatio="xMidYMax slice" aria-hidden="true"><Ridges /></svg>
          <div className="horizon-text">
            <h1>Hello{name ? `, ${name}` : ""}.</h1>
            <p className="horizon-status">Tell FocusOS when you like to work, and it will draw your day here and find free time inside those hours.</p>
            <a className="button" href="/#preferences">Set working hours</a>
          </div>
        </section>}
      <div className="ground">
        {me.kind === "unavailable" && <p role="alert" className="page-alert">Your profile is temporarily unavailable. Refresh to try again.</p>}
        <WorkComposer />
        {me.kind === "ok" && <>
          <div id="tasks"><TaskBoard /></div>
          <section id="schedule" className="schedule" aria-labelledby="schedule-heading">
            <h2 id="schedule-heading">Calendar</h2>
            <p className="section-lede">Your whole Google Calendar, month by month. Focus blocks FocusOS booked are marked in marigold.</p>
            <Conflicts />
            <MonthCalendar timezone={me.data.profile?.timezone} />
            <div className="calendar-area">
              <div className="booked" aria-labelledby="booked-heading">
                <h3 id="booked-heading">Booked by FocusOS</h3>
                <ScheduleBoard />
              </div>
              <div id="check-ins" className="check-in-area" aria-labelledby="check-ins-heading">
                <h3 id="check-ins-heading">How did it go?</h3>
                <CheckInPanel />
              </div>
            </div>
          </section>
          <section id="review" className="review-band" aria-labelledby="review-heading">
            <h2 id="review-heading">Your week</h2>
            <ReviewPanel />
          </section>
          <section className="more" aria-labelledby="more-heading">
            <h2 id="more-heading">Everything else</h2>
            <details id="email" className="drawer"><summary><span>Email priorities</span><small>Messages you labeled FocusOS in Gmail</small></summary><div className="drawer-body"><TriagePanel /></div></details>
            <details id="knowledge" className="drawer"><summary><span>Knowledge graph</span><small>How your notes connect to each other</small></summary><div className="drawer-body"><GraphPanel /></div></details>
            <details id="usage" className="drawer"><summary><span>AI usage</span><small>The last seven days</small></summary><div className="drawer-body"><UsagePanel /></div></details>
            <Preferences profile={me.data.profile} saved={params.saved} error={params.error} />
          </section>
        </>}
        <footer className="footer"><span>FocusOS keeps your work, notes and focus time in one place.</span><a href="/#composer">Back to the top</a></footer>
      </div>
    </> : <section className="welcome" aria-labelledby="welcome-heading">
      <Sunrise />
      <div className="welcome-text">
        <h1 id="welcome-heading">Say what is on your mind. FocusOS finds the time for it.</h1>
        <p>Write tasks, questions and plans the way you would say them. FocusOS saves the work, answers from your own notes, and books focus time on your Google Calendar.</p>
        <form action={signInWithGoogle}><button type="submit" className="button">Continue with Google</button></form>
      </div>
    </section>}
  </main>;
}
