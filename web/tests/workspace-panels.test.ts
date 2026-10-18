import { LOCALE } from "../src/app/locale";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkComposer } from "../src/app/work-composer";
import { MemorySearch } from "../src/app/memories/memory-search";

// Inject initial state for server-rendered UI cases, keeping real React hooks.
// These checks do not simulate typing, requests, or provider behavior.
const state = vi.hoisted(() => ({ values: [] as unknown[] }));
vi.mock("react", async importOriginal => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useState: (initial: unknown) => actual.useState(state.values.length ? state.values.shift() : initial),
  };
});
beforeEach(() => {
  state.values = [];
  vi.stubGlobal("React", React);
});
function composer(overrides: { text?: string; busy?: boolean; message?: string; error?: string; blocks?: unknown[]; defaultDuration?: boolean; warning?: string; answers?: unknown[]; issues?: string[] } = {}) {
  state.values = [overrides.text ?? "", overrides.busy ?? false, overrides.message ?? "",
    overrides.error ?? "", overrides.blocks ?? [], overrides.defaultDuration ?? false, overrides.warning ?? "",
    overrides.answers ?? [], overrides.issues ?? []];
  return renderToStaticMarkup(React.createElement(WorkComposer));
}
const answer = {
  id: "memory-nusa", text: "The FocusOS demo code is Nusa.",
  evidence_quote: "The FocusOS demo code is Nusa.", source_id: "source-nusa", match_kind: "semantic",
};
const related = {
  id: "memory-meeting", text: "The team meets on Monday.",
  evidence_quote: "Our team meets on Monday.", source_id: "source-meeting", match_kind: "semantic",
};
function memory(result: unknown = null, { query = "", busy = false, error = "" } = {}) {
  state.values = [query, result, busy, error];
  return renderToStaticMarkup(React.createElement(MemorySearch));
}

describe("What do you need to get done? rendering", () => {
  it("disables submission for whitespace and while processing", () => {
    expect(composer({ text: "   " })).toMatch(/<button[^>]*disabled/);
    const html = composer({ text: "Prepare checklist", busy: true });
    expect(html).toContain("Working...");
    expect(html).toMatch(/<textarea[^>]*disabled/);
    expect(html).toMatch(/<button[^>]*disabled/);
  });
  it("shows a saved task as status without claiming a Calendar event", () => {
    const html = composer({ message: "Saved 1 task(s) and 1 memory item(s)." });
    expect(html).toContain('role="status"');
    expect(html).toContain("Saved 1 task(s)");
    expect(html).not.toContain("Open in Google Calendar");
  });
  it("shows partial failure as an alert without hiding a completed event", () => {
    const html = composer({ error: "Already saved: 1 task(s). Could not schedule the next block.",
      blocks: [{ title: "Study mathematics", start: "2026-10-15T13:00:00+07:00",
        end: "2026-10-15T13:30:00+07:00", timezone: "Asia/Jakarta", link: "https://calendar.google.com/calendar/event?eid=synthetic" }] });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Already saved: 1");
    expect(html).toContain("Study mathematics");
    // Respect the runtime locale (e.g. 13.00 in Indonesian, 1:00 PM in English).
    const start = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Jakarta" }).format(new Date("2026-10-15T13:00:00+07:00"));
    const end = new Intl.DateTimeFormat(LOCALE, { timeStyle: "short", timeZone: "Asia/Jakarta" }).format(new Date("2026-10-15T13:30:00+07:00"));
    expect(html).toContain(`${start} - ${end} (Asia/Jakarta)`);
    expect(html).toContain("Asia/Jakarta");
    expect(html).toContain("https://calendar.google.com/calendar/event?eid=synthetic");
    expect(html).toContain('rel="noopener noreferrer"');
  });
  it("shows an availability shortfall alongside successfully created events", () => {
    const html = composer({ message: "Created 1 Calendar block.",
      warning: "Only 1 of 2 requested sessions fit. 1 session could not be scheduled.",
      blocks: [{ title: "Build the website", start: "2026-10-13T09:00:00+07:00",
        end: "2026-10-13T11:00:00+07:00", timezone: "Asia/Jakarta",
        link: "https://calendar.google.com/calendar/event?eid=synthetic" }] });
    expect(html).toContain('role="status"');
    expect(html).toContain('role="alert" class="composer-message composer-warning"');
    expect(html).toContain("Only 1 of 2 requested sessions fit");
    expect(html).toContain("Build the website");
    expect(html).toContain("https://calendar.google.com/calendar/event?eid=synthetic");
    expect(html).not.toContain("Could not finish this request");
  });
  it("keeps event times visible when no Google link was returned", () => {
    const html = composer({ blocks: [{ title: "Study", start: "2026-10-15T13:00:00+07:00",
      end: "2026-10-15T13:30:00+07:00", timezone: "Asia/Jakarta", link: null }], defaultDuration: true });
    expect(html).toContain("Study");
    expect(html).toContain("Duration used: 30 minutes.");
    expect(html).not.toContain("Open in Google Calendar");
  });
});

describe("answers inside the composer", () => {
  it("shows a grounded answer with the task it came from", () => {
    const html = composer({ message: "Checked 1 question(s) against your saved work.", answers: [{
      question: "Kapan deadline halaman web?", status: "answered", answer: "18 Oktober 2026.",
      references: [{ kind: "task", title: "Buat halaman web", detail: "open, due 2026-10-18" }] }] });
    expect(html).toContain("Kapan deadline halaman web?");
    expect(html).toContain("18 Oktober 2026.");
    expect(html).toContain("Buat halaman web");
    expect(html).toContain("open, due 2026-10-18");
    expect(html).toContain(">Task<");
  });
  it("says plainly when nothing saved answers the question", () => {
    const html = composer({ answers: [{ question: "Berapa budget proyek?", status: "no_reference", answer: null, references: [] }] });
    expect(html).toContain("Berapa budget proyek?");
    expect(html).toContain("No reference found in your saved tasks, memories, or scheduled work.");
    expect(html).not.toContain('class="composer-references"');
  });
  it("does not present a provider outage as a missing reference", () => {
    const html = composer({ answers: [{ question: "Kapan rapat?", status: "unavailable", answer: null, references: [] }] });
    expect(html).toContain("Could not check this question right now");
    expect(html).not.toContain("No reference found");
  });
  it("shows a failed part as an alert next to the parts that worked", () => {
    const html = composer({ message: "Saved 1 task(s) and 1 memory item(s).", issues: ["review desain: Not enough free time."] });
    expect(html).toContain('role="status"');
    expect(html).toContain('role="alert" class="composer-message composer-warning">review desain: Not enough free time.');
  });
});

describe("memory search rendering", () => {
  it("initially shows neither an answer nor a misleading no-match message", () => {
    const html = memory();
    expect(html).toMatch(/<button[^>]*disabled/);
    expect(html).not.toContain("ANSWER FROM SAVED MEMORY");
    expect(html).not.toContain("No confirmed memory");
  });
  it("disables the search button while waiting for an answer", () => {
    const html = memory(null, { query: "What is the demo code?", busy: true });
    expect(html).toContain("Finding answer...");
    expect(html).toMatch(/<button[^>]*disabled/);
  });
  it("shows the selected fact and exact evidence without source links or duplicate related entries", () => {
    const html = memory({ mode: "semantic_enabled", answer_status: "found", answer, matches: [related, answer] });
    expect(html).toContain("ANSWER FROM SAVED MEMORY");
    expect(html).toContain(`<blockquote>${answer.evidence_quote}</blockquote>`);
    expect(html).not.toContain('href="/activity');
    expect(html).toContain("Related memories (1)");
    expect(html).toContain(related.text);
    expect(html).toContain("Search mode: semantic.");
    // The selected fact appears in the answer and its quote, never again as a related row.
    expect(html.split(answer.text).length - 1).toBe(2);
  });
  it("does not display a related meeting fact as an answer to the demo-code question", () => {
    const html = memory({ mode: "semantic_enabled", answer_status: "not_found", answer: null, matches: [related] });
    expect(html).toContain("No confirmed memory directly answers this question.");
    expect(html).toContain("Related memories (1)");
    expect(html).not.toContain("ANSWER FROM SAVED MEMORY");
  });
  it("distinguishes unavailable answer verification from an empty result", () => {
    const html = memory({ mode: "lexical_fallback", answer_status: "unavailable", answer: null, matches: [related] });
    expect(html).toContain("Could not verify an answer right now");
    expect(html).toMatch(/<details[^>]*open/);
    expect(html).toContain("Search mode: keyword fallback.");
    expect(html).not.toContain("No confirmed memory directly answers");
  });
  it("shows empty results without a related-memory panel", () => {
    const html = memory({ mode: "semantic_enabled", answer_status: "not_found", answer: null, matches: [] });
    expect(html).toContain("No confirmed memory directly answers");
    expect(html).not.toContain("Related memories");
  });
  it("renders request errors as alerts and escapes untrusted stored text", () => {
    expect(memory(null, { error: "Authentication required" })).toContain('role="alert"');
    const unsafe = { ...answer, text: "<script>bad()</script>", evidence_quote: "<img src=x onerror=bad()>" };
    const html = memory({ mode: "semantic_enabled", answer_status: "found", answer: unsafe, matches: [unsafe] });
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&lt;img");
  });
});
