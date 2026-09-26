import { redirect } from "next/navigation";
import { getServerUser } from "@/server/auth/session";
import { readProfile } from "@/server/api/profile";
import { saveSettings } from "./actions";

export const dynamic = "force-dynamic";

const weekdays = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 7, label: "Sun" },
];

function timeFromMinutes(minutes: number): string {
  if (minutes === 1440) return "00:00";
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

export default async function Settings({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string; error?: string }>;
}) {
  const user = await getServerUser();
  if (!user) redirect("/");

  const [params, result] = await Promise.all([searchParams, readProfile()]);
  if (result.kind === "unauthorized") redirect("/");
  if (result.kind === "unavailable") {
    return (
      <main className="settings-page">
        <h1>Scheduling preferences</h1>
        <p role="alert">Could not load your preferences. Check the API and try again.</p>
        <a href="/settings">Retry</a>
      </main>
    );
  }

  const profile = result.profile;
  const hours = profile?.working_hours ?? {
    days: [1, 2, 3, 4, 5],
    start_minute: 540,
    end_minute: 1020,
  };
  const message =
    params.saved === "1"
      ? "Preferences saved."
      : params.error === "invalid"
        ? "Choose a valid IANA timezone, at least one day, and an end time after the start."
        : params.error === "unavailable"
          ? "Could not save your preferences. Please try again."
          : null;

  return (
    <main className="settings-page">
      <a href="/">← Home</a>
      <h1>Scheduling preferences</h1>
      <p>Set the timezone and local hours used for future focus blocks.</p>
      <p>Signed in{user.email ? ` as ${user.email}` : ""}.</p>
      {message ? <p role="status">{message}</p> : null}
      {!profile ? <p>These are suggested values. Review them before saving.</p> : null}
      <form action={saveSettings} className="settings-form">
        <label htmlFor="timezone">Timezone (IANA name)</label>
        <input
          id="timezone"
          name="timezone"
          type="text"
          required
          defaultValue={profile?.timezone ?? "Asia/Jakarta"}
          placeholder="Asia/Jakarta"
        />
        <fieldset>
          <legend>Working days</legend>
          <div className="weekday-options">
            {weekdays.map((day) => (
              <label key={day.value}>
                <input
                  type="checkbox"
                  name="days"
                  value={day.value}
                  defaultChecked={hours.days.includes(day.value)}
                />
                {day.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="time-fields">
          <label htmlFor="start">Start time
            <input id="start" name="start" type="time" required defaultValue={timeFromMinutes(hours.start_minute)} />
          </label>
          <label htmlFor="end">End time
            <input id="end" name="end" type="time" required defaultValue={timeFromMinutes(hours.end_minute)} />
          </label>
        </div>
        <p>Times use the timezone above. An end time of 00:00 means midnight.</p>
        <button type="submit">Save preferences</button>
      </form>
    </main>
  );
}
