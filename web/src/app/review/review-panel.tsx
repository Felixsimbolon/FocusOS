"use client";
import { useCallback, useEffect, useState } from "react";

export type WeekStats = {
  week_start: string; week_end: string; tasks_created: number; tasks_completed: number; tasks_overdue: number; overdue_titles: string[];
  blocks_scheduled: number; blocks_cancelled: number; focus_minutes: number; focus_by_project: { project: string; minutes: number }[];
  check_ins: number; planned_minutes_checked: number; actual_minutes_checked: number; model_calls: number;
};
export type Review = { week_start: string; stats: WeekStats; narrative: string | null; suggestions: string[]; narrative_source: "model" | "template" | null; saved: boolean };

export function hours(minutes: number): string {
  const whole = Math.floor(minutes / 60), rest = minutes % 60;
  return whole ? `${whole}h${rest ? ` ${rest}m` : ""}` : `${rest}m`;
}

export function accuracy(stats: WeekStats): string | null {
  if (!stats.planned_minutes_checked) return null;
  const ratio = stats.actual_minutes_checked / stats.planned_minutes_checked;
  return `${ratio.toFixed(1)}× planned`;
}

export function ReviewView({ review }: { review: Review }) {
  const { stats } = review;
  const peak = Math.max(1, ...stats.focus_by_project.map(item => item.minutes));
  const ratio = accuracy(stats);
  return <div className="review">
    <p className="review-facts">
      You booked <strong>{hours(stats.focus_minutes)}</strong> of focus across <strong>{stats.blocks_scheduled}</strong> {stats.blocks_scheduled === 1 ? "block" : "blocks"},
      finished <strong>{stats.tasks_completed}</strong> {stats.tasks_completed === 1 ? "task" : "tasks"} and added <strong>{stats.tasks_created}</strong>.
      {stats.tasks_overdue ? <> Right now <strong>{stats.tasks_overdue}</strong> open {stats.tasks_overdue === 1 ? "task is" : "tasks are"} past the deadline.</> : " Nothing is overdue."}
      {ratio ? <> By your {stats.check_ins} check-ins, work took <strong>{(stats.actual_minutes_checked / stats.planned_minutes_checked).toFixed(1)}×</strong> the planned time.</> : null}
    </p>
    {stats.focus_by_project.length > 0 && <figure className="review-projects"><figcaption>Focus by project</figcaption>
      <ul>{stats.focus_by_project.map(item => <li key={item.project}><span>{item.project}</span>
        <span className="review-bar" aria-hidden="true"><span style={{ width: `${(item.minutes / peak) * 100}%` }} /></span>
        <strong>{hours(item.minutes)}</strong></li>)}</ul></figure>}
    {stats.overdue_titles.length > 0 && <p className="review-overdue">Past deadline: {stats.overdue_titles.join(", ")}</p>}
    {review.narrative && <p className="review-narrative">{review.narrative}</p>}
    {review.suggestions.length > 0 && <ul className="review-suggestions" aria-label="Suggestions for next week">{review.suggestions.map((item, index) => <li key={index}>{item}</li>)}</ul>}
    {review.narrative_source === "template" && <p className="review-note">Written from a template because the AI summary was unavailable or mentioned a number not in your data.</p>}
  </div>;
}

export function ReviewPanel() {
  const [which, setWhich] = useState<"current" | "previous">("previous");
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback((week: "current" | "previous") => {
    setError("");
    fetch(`/api/product/review/${week}`, { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error()))
      .then(result => setReview(result as Review))
      .catch(() => setError("The weekly review is unavailable right now."));
  }, []);
  useEffect(() => { load(which); }, [load, which]);
  async function generate() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/product/review/${which}`, { method: "POST" });
      if (!response.ok) throw new Error();
      setReview(await response.json() as Review);
    } catch { setError("Could not write the review. Try again."); }
    finally { setBusy(false); }
  }
  return <div className="review-panel">
    <div className="review-controls">
      <div className="segmented" role="group" aria-label="Week">
        <button type="button" aria-pressed={which === "previous"} onClick={() => setWhich("previous")}>Last week</button>
        <button type="button" aria-pressed={which === "current"} onClick={() => setWhich("current")}>This week</button>
      </div>
      <button type="button" className="quiet" onClick={() => void generate()} disabled={busy}>{busy ? "Writing..." : review?.saved ? "Rewrite summary" : "Write summary"}</button>
    </div>
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {review && <ReviewView review={review} />}
  </div>;
}
