"use client";

import { useState } from "react";

type CalendarResult = {
  calendar: "primary";
  window_start: string;
  window_end: string;
  event_count: number;
  page_has_more: boolean;
};

export function CalendarPageProbe() {
  const [result, setResult] = useState<CalendarResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function readPage() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/integrations/google/calendar/probe", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) setError(body.error ?? "Could not read Calendar.");
      else setResult(body as CalendarResult);
    } catch {
      setError("Calendar probe is unavailable. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Calendar read test">
      <h2>Test primary Calendar read</h2>
      <p>Read at most one page for the next seven days. Event titles and details are not displayed or saved.</p>
      <button type="button" onClick={readPage} disabled={busy}>
        {busy ? "Reading?" : "Read Calendar page"}
      </button>
      {error ? <p role="alert">{error}</p> : null}
      {result ? (
        <dl role="status">
          <dt>Calendar</dt><dd>{result.calendar}</dd>
          <dt>Events in the next seven days</dt><dd>{result.event_count}</dd>
          <dt>More results</dt><dd>{result.page_has_more ? "Yes" : "No"}</dd>
        </dl>
      ) : null}
    </section>
  );
}
