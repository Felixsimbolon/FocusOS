"use client";
import { LOCALE } from "../locale";
import { useEffect, useState } from "react";

export type Settings = { morning_brief: boolean; brief_minute: number; block_reminders: boolean; reminder_minutes: 5 | 10 | 15 | 30;
  email: string | null; can_send: boolean; recent: { kind: string; status: string; sent_at: string | null; safe_error: string | null; created_at: string }[] };
const REASONS: Record<string, string> = {
  gmail_send_permission: "FocusOS is not allowed to send email yet. Use the link above to allow it.",
  google_not_connected: "Connect Google first.",
  gmail_send_rejected: "Gmail refused the message. Allow sending again from the link above.",
  provider_unavailable: "Gmail did not answer. FocusOS tries again on its next round.",
};
export const reason = (code: string | null) => (code && REASONS[code]) || "The email was not sent.";
const clock = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
const parse = (value: string) => { const [h, m] = value.split(":").map(Number); return h * 60 + m; };

export function sentLine(item: Settings["recent"][number]): string {
  const what = item.kind === "block_reminder" ? "Reminder" : "Morning brief";
  const when = new Intl.DateTimeFormat(LOCALE, { weekday: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(item.sent_at ?? item.created_at));
  if (item.status === "sent") return `${what}, sent ${when}`;
  if (item.status === "failed") return `${what} not sent, ${when}: ${reason(item.safe_error)}`;
  return `${what}, waiting to send (${when})`;
}

export function NotificationsForm({ settings, saving, onSave, onTest, testing }: {
  settings: Settings; saving: boolean; testing: boolean; onSave: (next: Omit<Settings, "email" | "can_send" | "recent">) => void; onTest: () => void;
}) {
  const [draft, setDraft] = useState({ morning_brief: settings.morning_brief, brief_minute: settings.brief_minute,
    block_reminders: settings.block_reminders, reminder_minutes: settings.reminder_minutes });
  return <div className="notifications">
    <p className="section-lede">FocusOS writes from your own Gmail{settings.email ? ` (${settings.email})` : ""} to the same address, so nothing new can read your inbox.</p>
    {!settings.can_send && <p className="notice">First <a href="/api/integrations/google/calendar-write/start">allow FocusOS to send email to you</a>. Google will ask once.</p>}
    <form className="notification-form" onSubmit={event => { event.preventDefault(); onSave(draft); }}>
      <label className="toggle"><input type="checkbox" checked={draft.morning_brief} onChange={event => setDraft({ ...draft, morning_brief: event.target.checked })} />
        Send me a morning brief at</label>
      <input aria-label="Morning brief time" type="time" value={clock(draft.brief_minute)} required onChange={event => setDraft({ ...draft, brief_minute: parse(event.target.value) })} />
      <label className="toggle"><input type="checkbox" checked={draft.block_reminders} onChange={event => setDraft({ ...draft, block_reminders: event.target.checked })} />
        Remind me before each focus block, about</label>
      <select aria-label="Minutes before a block" value={draft.reminder_minutes} onChange={event => setDraft({ ...draft, reminder_minutes: Number(event.target.value) as Settings["reminder_minutes"] })}>
        {[5, 10, 15, 30].map(value => <option key={value} value={value}>{value} minutes before</option>)}
      </select>
      <div className="inline-actions"><button type="submit" disabled={saving}>{saving ? "Saving..." : "Save notifications"}</button>
        <button type="button" className="quiet" disabled={testing || !settings.can_send} onClick={onTest}>{testing ? "Sending..." : "Send me a test brief now"}</button></div>
    </form>
    <p className="quiet-line">Emails go out within about five minutes of their time. Reminders only come for blocks FocusOS booked.</p>
    {settings.recent.length > 0 && <ul className="sent-list" aria-label="Recent notification emails">{settings.recent.map((item, index) => <li key={index} className={`sent-${item.status}`}>{sentLine(item)}</li>)}</ul>}
  </div>;
}

export function NotificationsPanel() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [notice, setNotice] = useState("");
  const load = () => fetch("/api/notifications/settings", { cache: "no-store" })
    .then(response => response.ok ? response.json() : Promise.reject(new Error()))
    .then(result => setSettings(result as Settings))
    .catch(() => setNotice("Email notifications are unavailable right now."));
  useEffect(() => { void load(); }, []);
  async function save(next: Omit<Settings, "email" | "can_send" | "recent">) {
    setSaving(true); setNotice("");
    try {
      const response = await fetch("/api/notifications/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
      if (!response.ok) throw new Error();
      setSettings(await response.json() as Settings); setNotice("Notifications saved.");
    } catch { setNotice("Could not save notifications. Try again."); }
    finally { setSaving(false); }
  }
  async function test() {
    setTesting(true); setNotice("");
    try {
      const response = await fetch("/api/notifications/test", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      setNotice(result.sent ? "Sent. Check your inbox." : reason(result.reason));
      void load();
    } catch (cause) { setNotice(cause instanceof Error && cause.message ? cause.message : "Could not send a test email."); }
    finally { setTesting(false); }
  }
  return <>{notice && <p role="status" className="notice">{notice}</p>}
    {settings ? <NotificationsForm key={settings.brief_minute + String(settings.morning_brief) + String(settings.block_reminders) + settings.reminder_minutes}
      settings={settings} saving={saving} testing={testing} onSave={next => void save(next)} onTest={() => void test()} />
      : !notice && <p className="loading-line">Loading notifications…</p>}</>;
}
