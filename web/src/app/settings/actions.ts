"use server";

import { redirect } from "next/navigation";
import { writeProfile } from "@/server/api/profile";

function minutesFromTime(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || !/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) {
    return null;
  }
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

export async function saveSettings(formData: FormData) {
  const timezone = formData.get("timezone");
  const days = formData.getAll("days").map(Number);
  const start = minutesFromTime(formData.get("start"));
  const endInput = formData.get("end");
  const end = endInput === "00:00" ? 1440 : minutesFromTime(endInput);

  if (
    typeof timezone !== "string" ||
    !timezone.trim() ||
    days.length === 0 ||
    days.some((day) => !Number.isInteger(day) || day < 1 || day > 7) ||
    start === null ||
    end === null
  ) {
    redirect("/settings?error=invalid");
  }

  const result = await writeProfile({
    timezone: timezone.trim(),
    working_hours: { days, start_minute: start, end_minute: end },
  });

  if (result === "unauthorized") redirect("/");
  if (result === "invalid") redirect("/settings?error=invalid");
  if (result === "unavailable") redirect("/settings?error=unavailable");
  redirect("/settings?saved=1");
}
