import { signInWithGoogle } from "./auth/actions";
import { Topbar } from "./topbar";
import { getMe } from "@/server/api/me";
import { loadHome } from "@/server/api/home";
import type { InitialTasks } from "./tasks/task-board";
import { TaskBoard } from "./tasks/task-board";
import { WorkComposer } from "./work-composer";
import { Preferences } from "./settings/preferences";
import { ScheduleBoard } from "./schedule/schedule-board";
import { UsagePanel } from "./usage/usage-panel";
import { FocusHud } from "./hud/focus-hud";
import { CheckInPanel } from "./check-ins/check-in-panel";
import { Conflicts } from "./schedule/conflicts";
import { MonthCalendar } from "./schedule/month-calendar";
import { RoutinesPanel } from "./routines/routines-panel";
import { ProjectsPanel } from "./projects/projects-panel";
import { NotesPanel } from "./notes/notes-panel";
import { NotificationsPanel } from "./notifications/notifications-panel";
import { TriagePanel } from "./activity/triage-panel";
import { GraphPanel } from "./knowledge/graph-panel";
import { ReviewPanel } from "./review/review-panel";
import { Ridges } from "./art/ridges";
import { Sunrise } from "./art/spots";

export const dynamic = "force-dynamic";


export default async function Home({ searchParams }: { searchParams: Promise<{ authError?: string; saved?: string; error?: string; source?: string }> }) {
  // Identity, profile and the first data are read together, so Home arrives already filled in.
  const [me, params, home] = await Promise.all([getMe(), searchParams, loadHome()]);
  const initialTasks = home.today && home.open && home.projects ? { today: home.today, open: home.open, projects: home.projects } as InitialTasks : null;
  const user = me.kind === "ok" ? me.data.user : me.kind === "unavailable" ? me.user : null;
  const profile = me.kind === "ok" ? me.data.profile : null;
  const name = me.kind === "ok" ? me.displayName : me.kind === "unavailable" ? me.user.name : undefined;
  const authError = params.authError === "callback" ? "Google sign-in did not complete. Try again."
    : params.authError === "start" ? "Could not start Google sign-in. Try again." : params.authError === "logout" ? "Could not sign out. Try again." : null;
  return <main className="home">
    <Topbar signedIn={!!user} />
    {authError && <p role="alert" className="page-alert">{authError}</p>}
    {user ? <>
      {profile ? <FocusHud timezone={profile.timezone} hours={profile.working_hours} name={name}
          initialDue={home.today ? home.today.tasks.length : null} initialBlocks={home.blocks as never} />
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
          <div id="tasks"><TaskBoard initial={initialTasks} /></div>
          <section id="schedule" className="schedule" aria-labelledby="schedule-heading">
            <h2 id="schedule-heading">Calendar</h2>
            <p className="section-lede">Your whole Google Calendar, month by month. Focus blocks FocusOS booked are marked in marigold.</p>
            <Conflicts />
            <MonthCalendar timezone={me.data.profile?.timezone} />
            <div className="calendar-area">
              <div className="booked" aria-labelledby="booked-heading">
                <h3 id="booked-heading">Booked by FocusOS</h3>
                <ScheduleBoard initial={home.blocks as never} />
              </div>
              <div id="check-ins" className="check-in-area" aria-labelledby="check-ins-heading">
                <h3 id="check-ins-heading">How did it go?</h3>
                <CheckInPanel />
              </div>
            </div>
          </section>
          <section id="projects" className="projects-section" aria-labelledby="projects-heading">
            <h2 id="projects-heading">Projects</h2>
            <p className="section-lede">Everything that belongs together: tasks, assignments, notes and the focus time booked for them.</p>
            <ProjectsPanel />
          </section>
          <section id="notes" className="notes-section" aria-labelledby="notes-heading">
            <h2 id="notes-heading">Notes</h2>
            <NotesPanel />
          </section>
          <section id="review" className="review-band" aria-labelledby="review-heading">
            <h2 id="review-heading">Your week</h2>
            <ReviewPanel />
          </section>
          <section className="more" aria-labelledby="more-heading">
            <h2 id="more-heading">Everything else</h2>
            <details id="routines" className="drawer"><summary><span>Routines</span><small>Recurring activities booked a week ahead</small></summary><div className="drawer-body"><RoutinesPanel /></div></details>
            <details id="notifications" className="drawer"><summary><span>Email notifications</span><small>Morning brief and reminders, from you to you</small></summary><div className="drawer-body"><NotificationsPanel /></div></details>
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
