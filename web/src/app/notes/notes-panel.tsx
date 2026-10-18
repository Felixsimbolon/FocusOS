"use client";
import { LOCALE } from "../locale";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type Job } from "../jobs/client";
import { followOrganization } from "../organization";

export type NoteSummary = { id: string; project_id: string | null; title: string; excerpt: string; version: number; updated_at: string };
type Note = { id: string; project_id: string | null; title: string; body: string; version: number };
type Project = { id: string; name: string };

export function filterNotes(notes: NoteSummary[], query: string, project: string): NoteSummary[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return notes.filter(note => (project === "all" || (project === "none" ? !note.project_id : note.project_id === project))
    && words.every(word => `${note.title} ${note.excerpt}`.toLowerCase().includes(word)));
}

export const saveLabel = (dirty: boolean, saving: boolean) => saving ? "Saving..." : dirty ? "Save note" : "Saved";

/** All notes on Home; on a project page, only that project's notes, and new ones belong to it. */
export function NotesPanel({ projectId }: { projectId?: string }) {
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState("all");
  const [note, setNote] = useState<Note | null>(null);
  const [draft, setDraft] = useState<{ title: string; body: string; project_id: string | null }>({ title: "", body: "", project_id: null });
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const editor = useRef<HTMLDivElement | null>(null);
  const dirty = !!note && (draft.title !== note.title || draft.body !== note.body || draft.project_id !== note.project_id);

  const load = useCallback(() => {
    fetch(projectId ? `/api/notes?project_id=${projectId}` : "/api/notes", { cache: "no-store" }).then(response => response.ok ? response.json() : []).then(result => setNotes(Array.isArray(result) ? result : [])).catch(() => setNotes([]));
    fetch("/api/projects", { cache: "no-store" }).then(response => response.ok ? response.json() : null).then(result => setProjects(Array.isArray(result?.projects) ? result.projects : [])).catch(() => undefined);
  }, [projectId]);
  const open = useCallback(async (id: string) => {
    const response = await fetch(`/api/notes/${id}`, { cache: "no-store" });
    if (!response.ok) { setNotice("This note is unavailable."); return; }
    const loaded = await response.json() as Note;
    setNote(loaded); setDraft({ title: loaded.title, body: loaded.body, project_id: loaded.project_id }); setNotice("");
    editor.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);
  useEffect(() => {
    load();
    const listener = (event: Event) => { const id = (event as CustomEvent).detail?.id; if (typeof id === "string") void open(id); };
    window.addEventListener("focusos:open-note", listener);
    return () => window.removeEventListener("focusos:open-note", listener);
  }, [load, open]);

  function create() {
    const fresh: Note = { id: crypto.randomUUID(), project_id: projectId ?? (projectFilter !== "all" && projectFilter !== "none" ? projectFilter : null), title: "", body: "", version: 0 };
    setNote(fresh); setDraft({ title: "", body: "", project_id: fresh.project_id }); setNotice("");
  }
  async function save() {
    if (!note || !draft.title.trim()) { setNotice("Give the note a title first."); return; }
    setSaving(true); setNotice("");
    try {
      const response = await fetch(`/api/notes/${note.id}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...draft, title: draft.title.trim(), expected_version: note.version }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not save this note.");
      setNote(result as Note); setDraft({ title: result.title, body: result.body, project_id: result.project_id }); load();
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : "Could not save this note."); }
    finally { setSaving(false); }
  }
  async function remove() {
    if (!note || note.version === 0) { setNote(null); return; }
    if (!window.confirm("Delete this note? This cannot be undone.")) return;
    const response = await fetch(`/api/notes/${note.id}/delete`, { method: "POST" });
    if (response.ok) { setNote(null); load(); } else setNotice("Could not delete this note.");
  }
  async function capture() {
    if (!note || dirty) { setNotice("Save the note first."); return; }
    setNotice("Finding tasks and facts in this note…");
    try {
      const response = await fetch(`/api/notes/${note.id}/capture`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_key: crypto.randomUUID() }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      const finished = await followOrganization(result.background_job as Job, () => undefined, new AbortController().signal);
      const tasks = Number(finished.result?.tasks_saved || 0), memories = Number(finished.result?.memories_saved || 0);
      setNotice(finished.status === "succeeded" ? `Saved ${tasks} task(s) and ${memories} memory item(s) from this note.` : "Could not finish reading this note. Try again.");
      window.dispatchEvent(new Event("focusos:tasks-changed"));
    } catch (cause) { setNotice(cause instanceof Error && cause.message ? cause.message : "Could not read this note."); }
  }

  const visible = useMemo(() => filterNotes(notes, query, projectFilter), [notes, query, projectFilter]);
  const projectName = (id: string | null) => projects.find(project => project.id === id)?.name;
  return <div className="notes">
    <div className="notes-list">
      <div className="notes-tools">
        <label className="sr-only" htmlFor="note-search">Search notes</label>
        <input id="note-search" type="search" placeholder="Search notes" value={query} onChange={event => setQuery(event.target.value)} />
        {!projectId && <><label className="sr-only" htmlFor="note-project">Filter by project</label>
        <select id="note-project" value={projectFilter} onChange={event => setProjectFilter(event.target.value)}>
          <option value="all">All projects</option><option value="none">No project</option>
          {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select></>}
        <button type="button" onClick={create}>New note</button>
      </div>
      {visible.length ? <ul className="note-items">{visible.map(item => <li key={item.id} className={note?.id === item.id ? "is-active" : ""}>
        <button type="button" onClick={() => void open(item.id)}><strong>{item.title}</strong>
          <small>{[projectName(item.project_id), new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" }).format(new Date(item.updated_at))].filter(Boolean).join(", ")}</small>
          {item.excerpt && <span>{item.excerpt}</span>}</button></li>)}</ul>
        : <p className="quiet-line">{notes.length ? "No note matches." : projectId ? "No notes for this project yet. What you write here becomes part of the project: questions about it use these notes." : "No notes yet. Write lecture notes, meeting notes or ideas; ask about them later in the composer."}</p>}
    </div>
    <div className="note-editor" ref={editor}>
      {note ? <form onSubmit={event => { event.preventDefault(); void save(); }}
        onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "s") { event.preventDefault(); void save(); } }}>
        <label className="sr-only" htmlFor="note-title">Note title</label>
        <input id="note-title" className="note-title" value={draft.title} maxLength={200} placeholder="Title" onChange={event => setDraft({ ...draft, title: event.target.value })} />
        {!projectId && <label className="note-project">Project<select value={draft.project_id ?? ""} onChange={event => setDraft({ ...draft, project_id: event.target.value || null })}>
          <option value="">No project</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>}
        <label className="sr-only" htmlFor="note-body">Note text</label>
        <textarea id="note-body" className="note-body" value={draft.body} maxLength={50000} placeholder="Write here…" onChange={event => setDraft({ ...draft, body: event.target.value })} />
        <div className="inline-actions">
          <button type="submit" disabled={saving || (!dirty && note.version > 0)}>{saveLabel(dirty || note.version === 0, saving)}</button>
          <button type="button" className="quiet" onClick={() => void capture()} disabled={note.version === 0}>Turn into tasks</button>
          <button type="button" className="quiet" onClick={() => void remove()}>Delete</button>
          <span className="quiet-line">{draft.body.length.toLocaleString()} / 50,000</span>
        </div>
      </form> : <p className="quiet-line">Pick a note, or start a new one. Notes are searched when you ask questions in the box above.</p>}
      {notice && <p role="status" className="notice">{notice}</p>}
    </div>
  </div>;
}
