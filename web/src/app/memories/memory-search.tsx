"use client";

import { FormEvent, useState } from "react";

type Match = {
  id: string; text: string; evidence_quote: string; source_id: string;
  match_kind: string;
};
type SearchResult = { mode: string; matches: Match[] };

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
        body: JSON.stringify({ query: query.trim(), limit: 5 }),
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

  return <section className="review-panel">
    <form className="task-form" onSubmit={(event) => void search(event)}>
      <label>Search confirmed memories
        <input value={query} onChange={(event) => setQuery(event.target.value)}
          maxLength={1000} required placeholder="When does the demo team meet?" />
      </label>
      <button type="submit" disabled={busy || !query.trim()}>{busy ? "Searching..." : "Search memories"}</button>
    </form>
    {error ? <p role="alert">{error}</p> : null}
    {result ? <>
      <p role="status">Search mode: {result.mode === "semantic_enabled" ? "semantic" :
        result.mode === "lexical_fallback" ? "keyword fallback" : result.mode}.
        {" "}Matches: {result.matches.length}.</p>
      {result.matches.length ? <ul className="task-list">{result.matches.map((match) =>
        <li key={match.id}>
          <strong>{match.text}</strong>
          <blockquote>{match.evidence_quote}</blockquote>
          <p>Match: {match.match_kind}</p>
          <a href={"/activity?source=" + match.source_id}>View source</a>
        </li>)}</ul> : <p>No confirmed memory matched this query.</p>}
    </> : null}
  </section>;
}
