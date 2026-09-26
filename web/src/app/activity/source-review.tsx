"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Source = {
  id: string; title: string; source_ref: string; normalized_body: string | null;
  body_hash: string; received_at: string; body_expires_at: string;
};
type Evidence = { source_ref: string; quote: string };
type TaskCandidate = {
  local_ref: string; title: string; description: string;
  deadline: { kind: "none" | "date" | "datetime" | "unresolved"; value: string | null; timezone: string | null };
  estimate_minutes: number | null; priority_hint: "low" | "normal" | "high" | "unspecified";
  confidence: number; evidence: Evidence[]; uncertainties: string[];
};
type Extraction = {
  id: string; status: "processing" | "ready" | "failed"; safe_error: string | null;
  ignored_item_keys: string[];
  validated_payload: {
    tasks: TaskCandidate[]; events: { title: string; uncertainties: string[] }[];
    facts: { text: string }[]; requests: { text: string }[];
    uncertainties: string[];
  } | null;
};
type Project = { id: string; name: string };

async function readJson<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "Request failed");
  return data as T;
}

function TaskReviewCard({ task, extractionId, ignored, projects, onChanged }: {
  task: TaskCandidate; extractionId: string; ignored: boolean; projects: Project[];
  onChanged: (next?: Extraction) => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState(task.priority_hint === "unspecified" ? "normal" : task.priority_hint);
  const [dueKind, setDueKind] = useState<"none" | "date" | "datetime">(
    task.deadline.kind === "unresolved" ? "none" : task.deadline.kind,
  );
  const [dueDate, setDueDate] = useState(task.deadline.kind === "date" ? task.deadline.value ?? "" : "");
  const [dueAt, setDueAt] = useState(task.deadline.kind === "datetime" ? task.deadline.value ?? "" : "");
  const [dueTimezone, setDueTimezone] = useState(task.deadline.timezone ?? "");
  const [estimate, setEstimate] = useState(task.estimate_minutes?.toString() ?? "");
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setMessage("");
    const reviewed = {
      title: title.trim(), description: description.trim() || null, priority,
      due_kind: dueKind, due_date: dueKind === "date" ? dueDate : null,
      due_at: dueKind === "datetime" ? dueAt : null,
      due_timezone: dueKind === "datetime" ? dueTimezone : null,
      estimate_minutes: estimate ? Number(estimate) : null,
      project_id: projectId || null,
    };
    try {
      await readJson(await fetch("/api/extractions/" + extractionId + "/confirm", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ local_ref: task.local_ref, task: reviewed }),
      }));
      setConfirmed(true);
      setMessage("Task saved. Open Today to see tasks due now or earlier.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save task");
    } finally { setBusy(false); }
  }

  async function toggleIgnore() {
    setBusy(true); setMessage("");
    try {
      const next = await readJson<Extraction>(await fetch("/api/extractions/" + extractionId + "/ignore", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ local_ref: task.local_ref, ignored: !ignored }),
      }));
      onChanged(next);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update review");
    } finally { setBusy(false); }
  }

  return <article className="review-card">
    <div className="task-board-heading"><h3>{task.title}</h3><span>{Math.round(task.confidence * 100)}% model confidence</span></div>
    <div className="review-evidence">
      <strong>Evidence from source</strong>
      {task.evidence.map((item, index) => <blockquote key={index}>{item.quote}</blockquote>)}
    </div>
    {task.uncertainties.length > 0 && <div className="review-uncertainty"><strong>Needs review</strong>
      <ul>{task.uncertainties.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </div>}
    {task.deadline.kind === "unresolved" && <p className="task-error">The source did not give a clear deadline. Choose one only if you know it.</p>}
    {ignored ? <p>Ignored for now. You can undo this decision.</p> : <form className="task-form" onSubmit={(event) => void confirm(event)}>
      <label>Task title<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required /></label>
      <label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} rows={2} /></label>
      <div className="review-grid">
        <label>Priority<select value={priority} onChange={(event) => setPriority(event.target.value as typeof priority)}>
          <option value="normal">Normal</option><option value="high">High</option><option value="low">Low</option>
        </select></label>
        <label>Deadline type<select value={dueKind} onChange={(event) => setDueKind(event.target.value as typeof dueKind)}>
          <option value="none">No deadline</option><option value="date">Calendar date</option><option value="datetime">Exact date and time</option>
        </select></label>
        {dueKind === "date" && <label>Due date<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} required /></label>}
        {dueKind === "datetime" && <>
          <label>ISO timestamp with offset<input value={dueAt} onChange={(event) => setDueAt(event.target.value)} placeholder="2026-09-27T14:00:00+07:00" required /></label>
          <label>IANA timezone<input value={dueTimezone} onChange={(event) => setDueTimezone(event.target.value)} placeholder="Asia/Jakarta" required /></label>
        </>}
        <label>Estimate (minutes)<input type="number" min={1} max={1440} value={estimate} onChange={(event) => setEstimate(event.target.value)} /></label>
        <label>Project<select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">No project</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
        </select></label>
      </div>
      <button type="submit" disabled={busy || confirmed}>{confirmed ? "Confirmed" : "Confirm task"}</button>
    </form>}
    <button type="button" className="secondary-button" onClick={() => void toggleIgnore()} disabled={busy || confirmed}>
      {ignored ? "Undo ignore" : "Ignore candidate"}
    </button>
    {message && <p role="status">{message}</p>}
  </article>;
}

export function SourceReview() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState<Source | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [title, setTitle] = useState("Synthetic email");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useRef<{ key: string; payload: string } | null>(null);

  const selectSource = useCallback(async (source: Source) => {
    setSelected(source); setExtraction(null);
    const response = await fetch("/api/sources/" + source.id + "/extraction", { cache: "no-store" });
    if (response.ok) {
      const data = await response.json() as { extraction: Extraction };
      setExtraction(data.extraction);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [sourceData, projectData] = await Promise.all([
          readJson<{ sources: Source[] }>(await fetch("/api/sources", { cache: "no-store" })),
          readJson<{ projects: Project[] }>(await fetch("/api/projects", { cache: "no-store" })),
        ]);
        setSources(sourceData.sources); setProjects(projectData.projects);
        const id = new URLSearchParams(window.location.search).get("source");
        if (id) {
          const found = sourceData.sources.find((item) => item.id === id);
          if (found) {
            await selectSource(found);
          } else {
            const detail = await readJson<{ source: Source }>(await fetch("/api/sources/" + encodeURIComponent(id), { cache: "no-store" }));
            setSources((current) => [detail.source, ...current]);
            await selectSource(detail.source);
          }
        }
      } catch { setMessage("Could not load sources or projects. Try reloading."); }
    })();
  }, [selectSource]);

  useEffect(() => {
    if (!selected || extraction?.status !== "processing") return;
    const timer = window.setTimeout(async () => {
      try {
        const data = await readJson<{ extraction: Extraction }>(await fetch(
          "/api/sources/" + selected.id + "/extraction", { cache: "no-store" }));
        setExtraction(data.extraction);
      } catch { setMessage("Could not refresh extraction status."); }
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [selected, extraction]);

  async function createSource(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    const payload = JSON.stringify({ title: title.trim(), text });
    if (!pending.current || pending.current.payload !== payload)
      pending.current = { key: crypto.randomUUID(), payload };
    try {
      const data = await readJson<{ source: Source }>(await fetch("/api/sources/manual", {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": pending.current.key },
        body: payload,
      }));
      pending.current = null;
      setSources((current) => [data.source, ...current.filter((item) => item.id !== data.source.id)]);
      await selectSource(data.source);
      setText("");
      setMessage("Source saved. Review its text before extracting.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save source"); }
    finally { setBusy(false); }
  }

  async function extract() {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const data = await readJson<{ extraction: Extraction }>(await fetch("/api/sources/" + selected.id + "/extract", { method: "POST" }));
      setExtraction(data.extraction);
      setMessage(data.extraction.status === "failed" ? "Extraction failed. You can retry." :
        data.extraction.status === "processing" ? "Extraction is running." : "Candidates are ready for review.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not extract source"); }
    finally { setBusy(false); }
  }

  return <section className="source-review">
    <form className="task-form review-panel" onSubmit={(event) => void createSource(event)}>
      <h2>Add a manual source</h2>
      <p>Paste one selected message or document excerpt. Text is available for 30 days, maximum 20 KB; expired text is cleared on a later source request. Extraction sends it to OpenAI.</p>
      <label>Source title<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required /></label>
      <label>Plain text<textarea rows={7} value={text} onChange={(event) => setText(event.target.value)} required /></label>
      <button type="submit" disabled={busy || !text.trim()}>Save source</button>
    </form>
    <div className="review-panel">
      <h2>Saved sources</h2>
      {sources.length === 0 ? <p>No sources yet.</p> : <ul className="source-list">
        {sources.map((source) => <li key={source.id}><button type="button" className={selected?.id === source.id ? "selected-source" : "secondary-button"}
          onClick={() => void selectSource(source)}>{source.title}</button></li>)}
      </ul>}
    </div>
    {selected && <div className="review-panel">
      <h2>{selected.title}</h2>
      <p>Received {new Date(selected.received_at).toLocaleString()} · Text expires {new Date(selected.body_expires_at).toLocaleDateString()}</p>
      {selected.normalized_body ? <pre className="source-text">{selected.normalized_body}</pre> :
        <p>Source text has expired. Existing task provenance remains available.</p>}
      <button type="button" onClick={() => void extract()} disabled={busy || !selected.normalized_body || extraction?.status === "processing"}>
        {extraction?.status === "ready" ? "Use saved extraction" : "Extract candidates"}
      </button>
      {extraction?.status === "processing" && <p role="status">Processing. This page will refresh the result.</p>}
      {extraction?.status === "failed" && <p role="alert">Extraction failed ({extraction.safe_error ?? "unknown"}). Retry when the provider is available.</p>}
      {extraction?.status === "ready" && extraction.validated_payload && <>
        <h2>Review candidates</h2>
        {extraction.validated_payload.uncertainties.map((item, index) => <p key={index} className="task-error">{item}</p>)}
        {extraction.validated_payload.tasks.length === 0 && <p>No actionable tasks were found.</p>}
        {extraction.validated_payload.tasks.map((task) => <TaskReviewCard key={task.local_ref}
          task={task} extractionId={extraction.id}
          ignored={extraction.ignored_item_keys.includes(task.local_ref)}
          projects={projects} onChanged={(next) => next && setExtraction(next)} />)}
        {extraction.validated_payload.events.length > 0 && <p>{extraction.validated_payload.events.length} event candidate(s) recognized for review only; no Calendar event was created.</p>}
        {extraction.validated_payload.requests.map((item, index) => <p key={index}>Request: {item.text}</p>)}
        {extraction.validated_payload.facts.map((item, index) => <p key={index}>Fact: {item.text}</p>)}
      </>}
    </div>}
    {message && <p role="status">{message}</p>}
    <a href="/">Back to Today</a>
  </section>;
}
