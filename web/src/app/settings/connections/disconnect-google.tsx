"use client";
import { useState } from "react";

export function DisconnectGoogle() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function disconnect() {
    if (!window.confirm("Disconnect Google? FocusOS will delete its saved tokens and stop Gmail sync and pending Calendar actions. Existing Google events remain.")) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/connections/google", { method: "DELETE" });
      if (!response.ok) throw new Error("Disconnect failed. Try again.");
      window.location.reload();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Disconnect failed."); setBusy(false); }
  }
  return <div><button type="button" className="secondary-button" disabled={busy} onClick={() => void disconnect()}>
    {busy ? "Disconnecting…" : "Disconnect Google"}
  </button>{message ? <p role="alert">{message}</p> : null}</div>;
}
