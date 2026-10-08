"use client";

import { FormEvent, useState } from "react";
import { PaginatedItems } from "../paginated-items";

type Match = {
  id: string; text: string; evidence_quote: string; source_id: string;
  match_kind: string;
};
type SearchResult = {
  mode: string;
  matches: Match[];
  answer_status: "not_requested" | "found" | "not_found" | "unavailable";
  answer: Match | null;
};

export function MemorySearch() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function search(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch("/api/memories/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), limit: 5, answer: true }),
      });
      const data = await response.json() as SearchResult | { error?: string };
      if (!response.ok || !("matches" in data)) {
        throw new Error("error" in data && data.error ? data.error : "Memory search unavailable");
      }
      setResult(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Memory search unavailable");
    } finally {
      setBusy(false);
    }
  }

  const selectedId = result?.answer?.id;
  const related = result?.matches.filter((match) => match.id !== selectedId) ?? [];
  return <section className="review-panel memory-search-panel">
    <form className="task-form" onSubmit={(event) => void search(event)}>
      <label>Ask about a saved fact
        <input value={query} onChange={(event) => setQuery(event.target.value)}
          maxLength={1000} required placeholder="What is the code name for the FocusOS demo project?" />
      </label>
      <button type="submit" disabled={busy || !query.trim()}>{busy ? "Finding answer..." : "Find answer"}</button>
    </form>
    {error ? <p role="alert">{error}</p> : null}
    {result ? <>
      {result.answer_status === "found" && result.answer ? <article className="memory-answer">
        <span className="activity-eyebrow">ANSWER FROM SAVED MEMORY</span>
        <h2>{result.answer.text}</h2>
        <blockquote>{result.answer.evidence_quote}</blockquote>
      </article> : <p role="status" className="memory-answer-empty">
        {result.answer_status === "unavailable"
          ? "Could not verify an answer right now. You can inspect the retrieved memories below."
          : "No confirmed memory directly answers this question."}
      </p>}
      {related.length ? <details className="memory-related" open={result.answer_status === "unavailable"}>
        <summary>Related memories ({related.length})</summary>
        <PaginatedItems key={related.map(match => match.id).join(",")} as="ul" className="task-list" label="related memories" pageSize={3} items={related.map((match) => <li key={match.id}>
          <strong>{match.text}</strong>
          <blockquote>{match.evidence_quote}</blockquote>
        </li>)} />
      </details> : null}
      <p className="memory-search-mode">Search mode: {result.mode === "semantic_enabled" ? "semantic" :
        result.mode === "lexical_fallback" ? "keyword fallback" : result.mode}.</p>
    </> : null}
  </section>;
}
