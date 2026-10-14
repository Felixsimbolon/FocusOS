import { signInWithGoogle, signOut } from "./auth/actions";
import { getMe } from "@/server/api/me";
import { TaskBoard } from "./tasks/task-board";
import { WorkComposer } from "./work-composer";
import { GmailSyncPanel } from "./activity/gmail-sync-panel";
import { Preferences } from "./settings/preferences";
import { ScheduleBoard } from "./schedule/schedule-board";
import { UsagePanel } from "./usage/usage-panel";
import { FocusHud } from "./hud/focus-hud";

export const dynamic = "force-dynamic";

function Brand() {
  return <a className="app-brand" href="/" aria-label="FocusOS home">
    <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3" /></svg></span>
    <span>Focus<span className="brand-os">OS</span></span>
  </a>;
}

export default async function Home({ searchParams }: { searchParams: Promise<{ authError?: string; saved?: string; error?: string; source?: string }> }) {
  const [me, params] = await Promise.all([getMe(), searchParams]);
  const user = me.kind === "ok" ? me.data.user : me.kind === "unavailable" ? me.user : null;
  const profile = me.kind === "ok" ? me.data.profile : null;
  const name = me.kind === "ok" ? me.displayName : me.kind === "unavailable" ? me.user.name : undefined;
  const authError = params.authError === "callback" ? "Google sign-in did not complete. Please try again."
    : params.authError === "start" ? "Could not start Google sign-in." : params.authError === "logout" ? "Could not sign out. Please try again." : null;
  return <main className="home-page">
    <div className="ambient" aria-hidden="true"><span className="ambient-orb orb-a" /><span className="ambient-orb orb-b" /><span className="ambient-grid" /></div>
    <header className="app-header">
      <div className="app-header-inner">
        <Brand />
        {user && <nav aria-label="Main navigation"><a href="/#composer">Write</a><a href="/#tasks">Tasks</a><a href="/#schedule">Calendar</a><a href="/#usage">Usage</a></nav>}
        {user && <div className="header-actions"><GmailSyncPanel /><form action={signOut}><button className="secondary-button" type="submit">Sign out</button></form></div>}
      </div>
    </header>
    {authError && <p role="alert" className="page-alert">{authError}</p>}
    {user ? <>
      {me.kind === "unavailable" && <p role="alert" className="page-alert">Your profile is temporarily unavailable. Refresh to try again.</p>}
      {profile ? <FocusHud timezone={profile.timezone} hours={profile.working_hours} name={name} />
        : <section className="hud hud-setup" aria-label="Get started">
          <div className="hud-greeting"><span className="hud-eyebrow"><span className="hud-pulse" aria-hidden="true" />Welcome</span>
            <h1>Hello{name ? `, ${name}` : ""}.</h1>
            <p className="hud-status">Set your working hours once, and FocusOS will find time for your work inside them.</p>
            <a className="control-button" href="/#preferences">Set working hours</a></div>
        </section>}
      <WorkComposer />
      {me.kind === "ok" && <>
        <div id="tasks" className="workspace-tasks"><TaskBoard /></div>
        <div className="workspace-secondary">
          <details id="schedule" className="home-panel schedule-panel" open><summary><span><span className="section-index">03</span>Scheduled work</span><small>Your Calendar</small></summary><div className="home-panel-body"><ScheduleBoard /></div></details>
          <details id="usage" className="home-panel usage-panel"><summary><span><span className="section-index">04</span>AI usage</span><small>Last 7 days</small></summary><div className="home-panel-body"><UsagePanel /></div></details>
        </div>
        <Preferences profile={me.data.profile} saved={params.saved} error={params.error} />
      </>}
      <footer className="workspace-footer"><span>FocusOS · your personal operating system for focus</span><a href="/#composer">Back to the top ↑</a></footer>
    </> : <section className="workspace-signin">
      <div className="signin-visual" aria-hidden="true"><span className="signin-ring ring-1" /><span className="signin-ring ring-2" /><span className="signin-ring ring-3" /><span className="signin-core" /></div>
      <div className="signin-copy">
        <span className="hud-eyebrow"><span className="hud-pulse" aria-hidden="true" />Personal focus system</span>
        <h1>Say what&apos;s on your mind. <span className="text-gradient">Get time for it.</span></h1>
        <p>Write tasks, questions and plans in one sentence. FocusOS saves the work, answers from your own notes, and books focus time on your Calendar.</p>
        <form action={signInWithGoogle}><button type="submit" className="primary-button">Continue with Google</button></form>
      </div>
    </section>}
  </main>;
}
