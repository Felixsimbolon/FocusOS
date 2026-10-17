/** Only the four settings fields, with their allowed values, reach the API. */
export function settingsBody(raw: string): string | null {
  try {
    const value = JSON.parse(raw);
    const keys = ["morning_brief", "brief_minute", "block_reminders", "reminder_minutes"];
    if (!value || Object.keys(value).some(key => !keys.includes(key))) return null;
    if (typeof value.morning_brief !== "boolean" || typeof value.block_reminders !== "boolean") return null;
    if (!Number.isInteger(value.brief_minute) || value.brief_minute < 0 || value.brief_minute > 1439) return null;
    if (![5, 10, 15, 30].includes(value.reminder_minutes)) return null;
    return JSON.stringify(Object.fromEntries(keys.map(key => [key, value[key]])));
  } catch { return null; }
}
