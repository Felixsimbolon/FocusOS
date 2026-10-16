"use client";
import { useCallback, useEffect, useState } from "react";

export type Priority = "urgent" | "normal" | "fyi";
export type TriageItem = { source_id: string; title: string | null; received_at: string | null; priority: Priority;
  model_priority: Priority | null; reason: string | null; corrected: boolean };
const LABEL: Record<Priority, string> = { urgent: "Urgent", normal: "Normal", fyi: "FYI" };

export function triageCounts(items: TriageItem[]): Record<Priority, number> {
  return items.reduce((counts, item) => ({ ...counts, [item.priority]: counts[item.priority] + 1 }), { urgent: 0, normal: 0, fyi: 0 });
}

export function TriageList({ items, saving, onChange }: { items: TriageItem[]; saving: string | null; onChange: (item: TriageItem, priority: Priority) => void }) {
  if (!items.length) return <p className="triage-empty">No prioritized email yet. Sync labeled Gmail messages and FocusOS will sort them into urgent, normal and FYI.</p>;
  const counts = triageCounts(items);
  return <div className="triage">
    <p className="triage-summary">{counts.urgent} urgent · {counts.normal} normal · {counts.fyi} FYI. Change a priority and FocusOS learns from it.</p>
    <ul className="triage-list" aria-label="Prioritized email">{items.map(item => <li key={item.source_id} className={`triage-item triage-${item.priority}`}>
      <div className="triage-text"><strong>{item.title || "(no subject)"}</strong>
        {item.reason && <small>{item.corrected ? "You set this priority." : item.reason}</small>}</div>
      <label className="triage-select"><span className="sr-only">Priority for {item.title || "this email"}</span>
        <select value={item.priority} disabled={saving === item.source_id} onChange={event => onChange(item, event.target.value as Priority)}>
          {(Object.keys(LABEL) as Priority[]).map(value => <option key={value} value={value}>{LABEL[value]}</option>)}
        </select></label>
    </li>)}</ul>
  </div>;
}

export function TriagePanel() {
  const [items, setItems] = useState<TriageItem[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    fetch("/api/product/triage", { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error()))
      .then(result => { setItems(Array.isArray(result) ? result : []); setError(""); })
      .catch(() => setError("Email priorities are unavailable right now."));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("focusos:sources-changed", load);
    return () => window.removeEventListener("focusos:sources-changed", load);
  }, [load]);
  async function change(item: TriageItem, priority: Priority) {
    setSaving(item.source_id); setError("");
    try {
      const response = await fetch(`/api/product/triage/${item.source_id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ priority }) });
      if (!response.ok) throw new Error();
      load();
    } catch { setError("Could not save this priority. Try again."); }
    finally { setSaving(null); }
  }
  return <>{error && <p role="alert" className="check-in-error">{error}</p>}<TriageList items={items} saving={saving} onChange={(item, priority) => void change(item, priority)} /></>;
}
