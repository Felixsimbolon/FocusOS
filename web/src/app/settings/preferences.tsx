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
      <p>Choose when FocusOS can schedule your work.</p>
      {saved === "1" && <p role="status">Preferences saved.</p>}
      {error && <p role="alert">{error === "invalid" ? "Choose a valid timezone, working days, and an end time after the start." : "Could not save preferences. Please try again."}</p>}
      <form action={saveSettings} className="settings-form">
        <label htmlFor="timezone">Timezone</label>
        <input id="timezone" name="timezone" required defaultValue={profile?.timezone ?? "Asia/Jakarta"} placeholder="Asia/Jakarta" />
        <fieldset><legend>Working days</legend><div className="weekday-options">
          {weekdays.map((label, index) => <label key={label}><input type="checkbox" name="days" value={index + 1} defaultChecked={hours.days.includes(index + 1)} />{label}</label>)}
        </div></fieldset>
        <div className="time-fields">
          <label htmlFor="start">Start time<input id="start" name="start" type="time" required defaultValue={time(hours.start_minute)} /></label>
          <label htmlFor="end">End time<input id="end" name="end" type="time" required defaultValue={time(hours.end_minute)} /></label>
        </div>
        <p>00:00 as the end time means midnight.</p>
        <button type="submit">Save preferences</button>
      </form>
    </div>
  </details>;
}
