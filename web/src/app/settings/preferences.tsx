import type { Me } from "@/server/api/me";
import { saveSettings } from "./actions";

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function time(minutes: number) {
  return minutes === 1440 ? "00:00" : `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}
export function Preferences({ profile, saved, error }: { profile: Me["profile"]; saved?: string; error?: string }) {
  const hours = profile?.working_hours ?? { days: [1, 2, 3, 4, 5], start_minute: 540, end_minute: 1020 };
  return <details id="preferences" className="home-panel preferences-panel" open={!!saved || !!error || !profile}>
    <summary><span>Preferences</span><small>{profile?.timezone ?? "Set your working hours"}</small></summary>
    <div className="home-panel-body">
      {saved === "1" && <p role="status" className="preferences-saved">Preferences saved. New plans will use these hours.</p>}
      {error && <p role="alert">{error === "invalid" ? "Choose a valid timezone, working days, and an end time after the start." : "Could not save preferences. Please try again."}</p>}
      <div className="preferences-layout">
        <aside className="preferences-intro"><span className="section-eyebrow">MAKE TIME YOURS</span><h3>A rhythm that works for you.</h3><p>Set the days and hours you want to work. FocusOS looks for free time inside this window.</p>
          <div className="preferences-current"><span>Current working window</span><strong>{time(hours.start_minute)} - {hours.end_minute === 1440 ? "24:00" : time(hours.end_minute)}</strong><small>{hours.days.map(day => weekdays[day - 1]).join(" / ")}</small></div>
        </aside>
        <form action={saveSettings} className="settings-form preferences-form">
          <div className="preference-field"><label htmlFor="timezone">Timezone</label><input id="timezone" name="timezone" required defaultValue={profile?.timezone ?? "Asia/Jakarta"} placeholder="Asia/Jakarta" aria-describedby="timezone-help" list="timezone-options" />
            <datalist id="timezone-options"><option value="Asia/Jakarta" /><option value="Asia/Makassar" /><option value="Asia/Jayapura" /><option value="Asia/Singapore" /><option value="UTC" /></datalist><small id="timezone-help">Use an IANA timezone, such as Asia/Jakarta.</small></div>
          <fieldset className="preferences-days"><legend>Working days</legend><div className="weekday-options">
            {weekdays.map((label, index) => <label key={label}><input type="checkbox" name="days" value={index + 1} defaultChecked={hours.days.includes(index + 1)} /><span>{label}</span></label>)}
          </div></fieldset>
          <div className="time-fields"><label htmlFor="start">Start time<input id="start" name="start" type="time" required defaultValue={time(hours.start_minute)} /></label><label htmlFor="end">End time<input id="end" name="end" type="time" required defaultValue={time(hours.end_minute)} /></label></div>
          <div className="preferences-footer"><small>End at 00:00 to work until midnight.</small><button type="submit">Save preferences</button></div>
        </form>
      </div>
    </div>
  </details>;
}
