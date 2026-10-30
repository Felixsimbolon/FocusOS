"use client";
import { useEffect, useRef, useState } from "react";
import { FILE_ACCEPT } from "@/lib/files";
import { type Job } from "../jobs/client";
import { LOCALE } from "../locale";
import { followOrganization } from "../organization";
import { LearningTrail, STATE_LABEL, trailAncestors, trailLevels, trailStates } from "./learning-trail";

export type Level = "understood" | "partly" | "not";
export type Analysis = {
  title: string; summary: string; project_name: string;
  deliverables: { text: string; quote: string }[];
  due: { raw_text: string | null; date: string | null; time: string | null };
  concepts: { name: string; why: string; study_minutes: number; kind?: "core" | "foundation"; prerequisites?: number[] }[];
  subtasks: { title: string; estimate_minutes: number; needs?: number[] }[];
};
export type Assignment = { id: string; title: string; status: "transcribed" | "questions" | "planned"; analysis: Analysis | null;
  understanding: Record<string, Level>; project_id: string | null; version: number };
type Project = { id: string; name: string };
/** What a project already knows about the plan's study tasks and their focus blocks. */
type Booked = { title: string; start: string; timezone?: string };
type StudyTask = { title: string; status: string };
type Stage = "pick" | "reading" | "analyzing" | "questions" | "plan" | "booking" | "done";

const LEVEL_LABEL: Record<Level, string> = { understood: "Sudah paham", partly: "Sebagian", not: "Belum" };

/** The tasks the plan will create: study sessions for what is not understood yet, then the subtasks (mirrors the API). */
export function previewTasks(analysis: Analysis, understanding: Record<string, Level>, project: string) {
  const study = analysis.concepts.flatMap((concept, index) => {
    const level = understanding[String(index)] ?? "not";
    if (level === "understood") return [];
    const minutes = level === "not" ? concept.study_minutes : Math.max(30, 15 * Math.ceil(concept.study_minutes / 2 / 15));
    return [{ title: `[${project}] Belajar: ${concept.name}`, minutes, kind: "study" as const }];
  });
  return [...study, ...analysis.subtasks.map(item => ({ title: `[${project}] ${item.title}`, minutes: item.estimate_minutes, kind: "work" as const }))];
}

export function stageOf(assignment: Assignment | null): Stage {
  if (!assignment) return "pick";
  if (!assignment.analysis) return "analyzing";
  if (assignment.status === "planned") return "done";
  const answered = assignment.analysis.concepts.every((_, index) => String(index) in assignment.understanding);
  return answered ? "plan" : "questions";
}

/** Answering "understood" also answers the prerequisites not answered yet: you cannot know B without A. */
export function answersFor(analysis: Analysis, understanding: Record<string, Level>, index: number, level: Level): Record<string, Level> {
  const answers: Record<string, Level> = { [String(index)]: level };
  if (level === "understood")
    for (const before of trailAncestors(analysis.concepts, index)) if (!(String(before) in understanding)) answers[String(before)] = "understood";
  return answers;
}

/** A study task's state from the project's tasks and blocks, matched by the "Belajar: <concept>" title the plan gives it. */
export function studyFinder(analysis: Analysis, tasks: StudyTask[], blocks: Booked[]) {
  return (index: number) => {
    const suffix = `Belajar: ${analysis.concepts[index].name}`;
    const task = tasks.find(item => item.title.endsWith(suffix));
    const block = blocks.filter(item => item.title.endsWith(suffix)).sort((a, b) => a.start.localeCompare(b.start))[0];
    if (!task && !block) return null;
    return { done: task?.status === "done", scheduled: block ? new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short",
      hour: "2-digit", minute: "2-digit", timeZone: block.timezone }).format(new Date(block.start)) : null };
  };
}

export function hours(minutes: number) {
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return h ? `${h} j${m ? ` ${m} m` : ""}` : `${m} m`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "Could not finish this step. Try again.");
  return body as T;
}

const STEPS = ["Baca tugas", "Pahami konsep", "Rencanakan", "Jadwalkan"];

export function Steps({ stage }: { stage: Stage }) {
  const current = stage === "pick" || stage === "reading" || stage === "analyzing" ? 0 : stage === "questions" ? 1 : stage === "plan" ? 2 : 3;
  return <ol className="steps" aria-label="Assignment steps">{STEPS.map((label, index) =>
    <li key={label} className={index < current ? "is-done" : index === current ? "is-current" : ""} aria-current={index === current ? "step" : undefined}>{label}</li>)}</ol>;
}

export function AssignmentFlow({ initial, projects, onClose, onChanged, tasks = [], blocks = [] }: { initial: Assignment | null; projects: Project[];
  onClose: () => void; onChanged: () => void; tasks?: StudyTask[]; blocks?: Booked[] }) {
  const [assignment, setAssignment] = useState<Assignment | null>(initial);
  const [stage, setStage] = useState<Stage>(stageOf(initial));
  const [error, setError] = useState("");
  const [projectChoice, setProjectChoice] = useState<string>(initial?.project_id ?? "new");
  const [projectName, setProjectName] = useState(initial?.analysis?.project_name ?? "");
  const [result, setResult] = useState("");
  const [booked, setBooked] = useState<Booked[]>([]);

  // Resuming an uploaded but unanalysed assignment continues where it stopped.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current || !initial || initial.analysis) return;
    resumed.current = true; void analyze(initial);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);
  async function analyze(current: Assignment) {
    setStage("analyzing"); setError("");
    try {
      const analyzed = await call<Assignment>(`/api/assignments/${current.id}/analyze`, { method: "POST" });
      setAssignment(analyzed); setProjectName(analyzed.analysis?.project_name ?? ""); setStage(stageOf(analyzed)); onChanged();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not analyze."); setStage("analyzing"); }
  }
  function pick() {
    const input = document.createElement("input");
    input.type = "file"; input.accept = FILE_ACCEPT;
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file) return;
      if (file.size > 3_000_000) { setError("Attach a file of at most 3 MB."); return; }
      setStage("reading"); setError("");
      const form = new FormData(); form.set("file", file); form.set("request_key", crypto.randomUUID());
      try {
        const created = await call<Assignment>("/api/assignments", { method: "POST", body: form });
        setAssignment(created); onChanged(); await analyze(created);
      } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not read this file."); setStage("pick"); }
    };
    input.click();
  }
  async function answerConcept(index: number, level: Level) {
    if (!assignment) return; setError("");
    try {
      const saved = await call<Assignment>(`/api/assignments/${assignment.id}/understanding`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: assignment.version, answers: answersFor(assignment.analysis!, assignment.understanding, index, level) }) });
      setAssignment(saved);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save this answer."); }
  }
  async function removePrerequisite(concept: number, prerequisite: number) {
    if (!assignment) return; setError("");
    try {
      const saved = await call<Assignment>(`/api/assignments/${assignment.id}/graph`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: assignment.version, concept, remove_prerequisite: prerequisite }) });
      setAssignment(saved);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not change the learning path."); }
  }
  async function book() {
    if (!assignment) return; setStage("booking"); setError("");
    const project = projectChoice === "new" ? { project_name: projectName.trim() || assignment.analysis?.project_name || assignment.title } : { project_id: projectChoice };
    try {
      const planned = await call<{ assignment: Assignment; background_job: Job | null; created: number; unscheduled?: number }>(`/api/assignments/${assignment.id}/plan`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: assignment.version, request_key: crypto.randomUUID(), ...project }) });
      setAssignment(planned.assignment);
      window.dispatchEvent(new Event("focusos:tasks-changed"));
      if (planned.background_job) {
        const finished = await followOrganization(planned.background_job, () => undefined, new AbortController().signal);
        const blocks = Number(finished.result?.blocks_scheduled || 0);
        const made = Array.isArray(finished.result?.blocks) ? finished.result.blocks as Booked[] : [];
        setBooked(made.filter(item => typeof item?.title === "string" && typeof item?.start === "string"));
        const waiting = Array.isArray(finished.result?.schedules) ? (finished.result.schedules as { code?: string }[]).filter(item => item.code === "prerequisite_unscheduled").length : 0;
        setResult(`${planned.created} task dibuat, ${blocks} di antaranya sudah dijadwalkan di Calendar.${planned.unscheduled ? ` ${planned.unscheduled} sisanya belum dijadwalkan; jadwalkan nanti lewat composer.` : ""}${blocks < Math.min(planned.created, 12) ? " Sebagian tidak muat di jam kerja 7 hari ke depan." : ""}${waiting ? ` ${waiting} menunggu prasyaratnya terjadwal dulu, jadi belum dijadwalkan.` : ""}`);
      } else setResult("Rencana untuk tugas ini sudah dibuat sebelumnya.");
      window.dispatchEvent(new Event("focusos:schedule-changed"));
      setStage("done"); onChanged();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not plan this assignment."); setStage("plan"); }
  }

  const analysis = assignment?.analysis;
  const planned = stage === "done" || assignment?.status === "planned";
  const study = analysis ? studyFinder(analysis, tasks, [...blocks, ...booked]) : () => null;
  const states = analysis ? trailStates(analysis.concepts, assignment!.understanding, planned, study) : [];
  const levels = analysis ? trailLevels(analysis.concepts) : [];
  const anchor = (index: number) => `concept-${assignment?.id ?? "new"}-${index}`;
  const preview = analysis ? previewTasks(analysis, assignment!.understanding, projectChoice === "new" ? (projectName.trim() || analysis.project_name) : projects.find(p => p.id === projectChoice)?.name ?? "") : [];
  return <section className="assignment" aria-label="Assignment planner">
    <div className="assignment-head"><Steps stage={stage} /><button type="button" className="quiet" onClick={onClose}>Close</button></div>
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {stage === "pick" && <div className="assignment-pick"><p className="insight">Upload brief tugas: PDF, Word (.docx), Markdown (.md) atau foto. FocusOS akan membaca isinya, menanyakan bagian mana yang sudah kamu pahami, lalu memecahnya menjadi sesi belajar dan subtask yang dijadwalkan.</p>
      <button type="button" className="button" onClick={pick}>Pilih file tugas</button></div>}
    {(stage === "reading" || (stage === "analyzing" && !error)) && <p role="status" className="assignment-working">{stage === "reading" ? "Membaca dokumen…" : "Menganalisis tugas…"}</p>}
    {stage === "analyzing" && error && assignment && <button type="button" onClick={() => void analyze(assignment)}>Coba analisis lagi</button>}
    {analysis && stage !== "pick" && <div className="assignment-brief">
      <h3>{analysis.title}</h3>
      <p className="insight">{analysis.summary}</p>
      <p className="quiet-line">{analysis.due.date ? `Deadline ${analysis.due.date}${analysis.due.time ? ` ${analysis.due.time}` : ""} (“${analysis.due.raw_text}”)` : "Tidak ada deadline yang tertulis di dokumen."}</p>
      {analysis.deliverables.length > 0 && <ul className="deliverables" aria-label="Deliverables">{analysis.deliverables.map((item, index) => <li key={index}>{item.text}</li>)}</ul>}
    </div>}
    {analysis && (stage === "questions" || stage === "plan" || stage === "done") && <div className="concepts">
      <p className="concepts-lead">{planned ? "Jalur belajarnya: dari dasar di kaki gunung sampai tugasnya di puncak." :
        "Ini jalur belajar untuk tugas ini, dari dasar sampai puncak. Sudah paham bagian mana? Kalau kamu paham satu konsep, prasyaratnya ikut ditandai."}</p>
      <LearningTrail concepts={analysis.concepts} states={states} summit={analysis.title} anchor={anchor}
        dates={analysis.concepts.map((_, index) => study(index)?.scheduled ?? null)} />
      <ol className="learning-order" aria-label="Urutan belajar">{analysis.concepts.map((concept, index) => {
        const chosen = assignment!.understanding[String(index)];
        const before = (concept.prerequisites ?? []).filter(p => p < analysis.concepts.length);
        return <li key={index} id={anchor(index)} className={`is-${states[index]}${chosen ? ` is-answered level-${chosen}` : ""}`}
          style={{ ["--level" as string]: levels[index] - 1 }}>
          <p className="concept-name">{concept.name}{concept.kind === "foundation" && <span className="concept-kind">dasar</span>}</p>
          <p className="quiet-line">{concept.why}</p>
          {before.length > 0 && <p className="concept-needs">Setelah {before.map(p => <span key={p} className="concept-need">
            {analysis.concepts[p].name}
            {!planned && <button type="button" className="quiet concept-unlink" aria-label={`Hapus ${analysis.concepts[p].name} sebagai prasyarat ${concept.name}`}
              onClick={() => void removePrerequisite(index, p)}>hapus</button>}</span>)}</p>}
          {planned ? <p className="concept-state">{STATE_LABEL[states[index]]}{study(index)?.scheduled ? `, ${study(index)!.scheduled}` : ""}</p>
            : <div className="choices" role="group" aria-label={`Sudah paham ${concept.name}?`}>
              {(Object.keys(LEVEL_LABEL) as Level[]).map(level => <button key={level} type="button" aria-pressed={chosen === level} onClick={() => void answerConcept(index, level)}>{LEVEL_LABEL[level]}</button>)}
            </div>}
        </li>;
      })}</ol>
    </div>}
    {analysis && stage === "plan" && <div className="plan-preview">
      <h3>Rencananya</h3>
      <div className="field-row">
        <label>Proyek<select value={projectChoice} onChange={event => setProjectChoice(event.target.value)}>
          <option value="new">Proyek baru</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        {projectChoice === "new" && <label>Nama proyek<input value={projectName} maxLength={100} onChange={event => setProjectName(event.target.value)} /></label>}
      </div>
      <ul className="preview-list">{preview.map((task, index) => <li key={index} className={`preview-${task.kind}`}><span>{task.title}</span><small>{hours(task.minutes)}</small></li>)}</ul>
      <p className="quiet-line">Total {hours(preview.reduce((sum, task) => sum + task.minutes, 0))}. Sesi belajar dijadwalkan mengikuti jalurnya: satu topik baru dimulai setelah prasyaratnya selesai, semuanya di jam kerja dan sebelum deadline.</p>
      <button type="button" className="button" onClick={() => void book()}>Buat task dan jadwalkan</button>
    </div>}
    {stage === "booking" && <p role="status" className="assignment-working">Membuat task dan mencari waktu kosong…</p>}
    {stage === "done" && <p role="status" className="notice notice-ok">{result || "Tugas ini sudah direncanakan. Task-nya ada di Today dan di proyeknya."}</p>}
  </section>;
}
