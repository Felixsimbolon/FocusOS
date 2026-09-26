"use client";

import { type FormEvent, useState } from "react";

type ProbeResult = {
  message_id: string;
  internal_date_ms: number | null;
  label_count: number;
  text_body_bytes: number;
};

export function GmailMessageProbe() {
  const [messageId, setMessageId] = useState("");
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch(
        "/api/integrations/google/gmail/messages/" + encodeURIComponent(messageId.trim()),
        { cache: "no-store" },
      );
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? "Could not read this message.");
      } else {
        setResult(body as ProbeResult);
      }
    } catch {
      setError("Gmail probe is unavailable. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Gmail read test">
      <h2>Test one Gmail message</h2>
      <p>
        Enter the ID of a synthetic test email. You can obtain it from Gmail's
        <a href="https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list" target="_blank" rel="noreferrer"> messages.list API</a>.
        FocusOS reads the selected message in memory and does not save or display its contents.
      </p>
      <form onSubmit={submit}>
        <label htmlFor="gmail-message-id">Gmail message ID</label>
        <input
          id="gmail-message-id"
          value={messageId}
          onChange={(event) => setMessageId(event.target.value)}
          required
          maxLength={128}
          pattern="[A-Za-z0-9_-]{1,128}"
        />
        <button type="submit" disabled={busy}>{busy ? "Reading?" : "Read selected message"}</button>
      </form>
      {error ? <p role="alert">{error}</p> : null}
      {result ? (
        <dl role="status">
          <dt>Message ID</dt><dd>{result.message_id}</dd>
          <dt>Labels returned</dt><dd>{result.label_count}</dd>
          <dt>Plain-text body size</dt><dd>{result.text_body_bytes} bytes (read in memory only)</dd>
        </dl>
      ) : null}
    </section>
  );
}
