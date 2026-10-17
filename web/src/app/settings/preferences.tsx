import type { Me } from "@/server/api/me";
import { saveSettings } from "./actions";

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function time(minutes: number) {
  return minutes === 1440 ? "00:00" : `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}
export function Preferences({ profile, saved, error }: { profile: Me["profile"]; saved?: string; error?: string }) {
  const hours = profile?.working_hours ?? { days: [1, 2, 3, 4, 5], start_minute: 540, end_minute: 1020 };
  const span = `${time(hours.start_minute)} to ${hours.end_minute === 1440 ? "24:00" : time(hours.end_minute)}`;
  return <details id="preferences" className="drawer" open={!!saved || !!error || !profile}>
    <summary><span>Working hours</span><small>{profile ? `${span}, ${profile.timezone}` : "Not set yet"}</small></summary>
    <div className="drawer-body">
      {saved === "1" && <p role="status" className="notice notice-ok">Preferences saved. New plans use these hours, and the sun on your horizon follows them.</p>}
      {error && <p role="alert" className="notice notice-error">{error === "invalid" ? "Choose a valid timezone, at least one working day, and an end time after the start." : "Could not save preferences. Try again."}</p>}
      <p className="section-lede">FocusOS only looks for free time inside these hours.</p>
      <form action={saveSettings} className="preferences">
        <fieldset className="days"><legend>Working days</legend>
          {weekdays.map((label, index) => <label key={label} className="day-toggle"><input type="checkbox" name="days" value={index + 1} defaultChecked={hours.days.includes(index + 1)} /><span>{label}</span></label>)}
        </fieldset>
        <div className="field-row">
          <label htmlFor="start">From<input id="start" name="start" type="time" required defaultValue={time(hours.start_minute)} /></label>
          <label htmlFor="end">Until<input id="end" name="end" type="time" required defaultValue={time(hours.end_minute)} /></label>
          <label htmlFor="timezone">Timezone<input id="timezone" name="timezone" required defaultValue={profile?.timezone ?? "Asia/Jakarta"} placeholder="Asia/Jakarta" aria-describedby="timezone-help" list="timezone-options" /></label>
          <datalist id="timezone-options"><option value="Asia/Jakarta" /><option value="Asia/Makassar" /><option value="Asia/Jayapura" /><option value="Asia/Singapore" /><option value="UTC" /></datalist>
        </div>
        <p id="timezone-help" className="quiet-line">Use a timezone name such as Asia/Jakarta. End at 00:00 to work until midnight.</p>
        <button type="submit">Save preferences</button>
      </form>
    </div>
  </details>;
}
