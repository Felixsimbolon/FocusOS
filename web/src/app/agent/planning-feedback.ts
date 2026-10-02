/** Safe, actionable messages shared by planning and the request proxy. */
const reasons: Record<string, string> = {
  invalid_plan: "The planner could not produce a valid result. Retry this request; no event was confirmed.",
  invalid_plan_schema: "The AI returned an unreadable planning result. Retry this request.",
  unknown_task_reference: "The AI selected an unavailable task. Start a new plan using an active task title.",
  unknown_memory_reference: "The AI returned an unsupported memory reference. Retry this request.",
  invalid_time_constraint: "The requested time could not be resolved safely. Specify a day and a clear time range.",
  planning_timeout: "The AI took too long to respond. Retry this request.",
  provider_unconfigured: "The server is missing its Gemini configuration.",
  provider_unavailable: "Gemini is temporarily unavailable. Try again later.",
  context_oversize: "There is too much context for this plan. Use a shorter request or fewer active tasks.",
  run_expired: "This run has expired. Start a new plan.",
  profile_required: "Save your timezone and working hours in Settings, then submit again.",
  profile_changed: "Your scheduling timezone changed. Start a new plan with the current settings.",
  calendar_snapshot_incomplete: "Calendar availability could not be read completely. Start a new plan.",
  task_deadline_invalid: "The saved task deadline is invalid. Correct it and start a new plan.",
  request_options_changed: "This request already started with different options. Start a new plan.",
};

export function describePlanningFailure(code: string | null): string {
  return code && reasons[code] ? reasons[code] : "Planning could not finish safely. Start a new plan or try again later.";
}

export function buildPlanningRequest(command: string, duration: string, allowSplit: boolean, requestKey: string) {
  const text = command.trim();
  if (!text || text.length > 1000) throw new Error("Describe your plan using 1 to 1000 characters.");
  const minutes = duration.trim() ? Number(duration) : null;
  if (minutes !== null && (!Number.isInteger(minutes) || minutes < 15 || minutes > 480)) {
    throw new Error("Choose a duration between 15 and 480 whole minutes, or leave the field empty.");
  }
  return { request_key: requestKey, command: text, duration_minutes: minutes,
    allow_split: allowSplit, auto_calendar: true };
}
