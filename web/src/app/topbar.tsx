import { signOut } from "./auth/actions";
import { GmailSyncPanel } from "./activity/gmail-sync-panel";
import { ThemeToggle } from "./theme-toggle";

export function Brand() {
  return <a className="brand" href="/" aria-label="FocusOS home">
    <svg viewBox="0 0 32 20" aria-hidden="true"><path d="M2 18 H30" /><path d="M7 18 A9 9 0 0 1 25 18" /><circle cx="16" cy="11" r="3.2" /></svg>
    FocusOS
  </a>;
}

/** The bar over the sky on every signed-in page; signed out it shows only the brand and the theme switch. */
export function Topbar({ signedIn }: { signedIn: boolean }) {
  return <header className="topbar">
    <Brand />
    {!signedIn && <div className="topbar-actions"><ThemeToggle /></div>}
    {signedIn && <nav aria-label="Main navigation"><a href="/#composer">Write</a><a href="/#tasks">Today</a><a href="/#schedule">Calendar</a><a href="/#projects">Projects</a><a href="/#notes">Notes</a><a href="/#review">Review</a></nav>}
    {signedIn && <div className="topbar-actions"><ThemeToggle /><GmailSyncPanel /><form action={signOut}><button className="quiet" type="submit">Sign out</button></form></div>}
  </header>;
}
