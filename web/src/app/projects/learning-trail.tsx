"use client";
import { useState } from "react";

/** An assignment's learning path drawn as a trail up a mountain: foundations at the foot, the assignment at the summit,
 * each path a prerequisite. The numbered list beside it is the same path in learning order, and the one screen readers use. */

export type TrailConcept = { name: string; kind?: "core" | "foundation"; prerequisites?: number[] };
export type TrailState = "known" | "done" | "scheduled" | "next" | "locked" | "open";
export type TrailNode = { index: number; level: number; x: number; y: number };

// Each concept gets at least COLUMN of width, so a wide row grows the map (it scrolls) instead of piling names up.
const WIDTH = 720, COLUMN = 160, ROW = 96, LINE = 15, TOP = 86, FOOT = 64, LABEL_CHARS = 20, LABEL_LINES = 3;

export const STATE_LABEL: Record<TrailState, string> = {
  known: "Sudah paham", done: "Selesai dipelajari", scheduled: "Terjadwal", next: "Bisa dipelajari sekarang", locked: "Menunggu prasyarat", open: "Belum dijawab",
};

/** 1 for a concept with no prerequisites, else one more than its highest prerequisite. Unknown references are ignored. */
export function trailLevels(concepts: TrailConcept[]): number[] {
  const memo: number[] = [];
  const level = (index: number, seen: Set<number>): number => {
    if (memo[index]) return memo[index];
    const prerequisites = (concepts[index].prerequisites ?? []).filter(p => p >= 0 && p < concepts.length && !seen.has(p));
    const value = 1 + Math.max(0, ...prerequisites.map(p => level(p, new Set([...seen, index]))));
    memo[index] = value;
    return value;
  };
  return concepts.map((_, index) => level(index, new Set([index])));
}

/** A name broken into lines at word boundaries, so the whole name shows. Only a name past `max` lines is shortened. */
export function labelLines(text: string, width = LABEL_CHARS, max = LABEL_LINES): string[] {
  const lines: string[] = [];
  for (const word of text.trim().split(/\s+/).filter(Boolean)) {
    const last = lines.length - 1;
    if (last >= 0 && `${lines[last]} ${word}`.length <= width) lines[last] = `${lines[last]} ${word}`;
    else lines.push(word);
  }
  if (lines.length <= max) return lines;
  const kept = lines.slice(0, max);
  kept[max - 1] = `${kept[max - 1].slice(0, width - 1)}…`;
  return kept;
}

/** Rows bottom-up by level; within a row, a concept sits near the prerequisites it climbs from, to keep paths from crossing. */
export function trailLayout(concepts: TrailConcept[], summitName = ""): {
  nodes: TrailNode[]; width: number; height: number; summit: { x: number; y: number };
} {
  const levels = trailLevels(concepts), top = Math.max(1, ...levels);
  const widest = Math.max(1, ...Array.from({ length: top }, (_, level) => levels.filter(value => value === level + 1).length));
  const width = Math.max(WIDTH, (widest + 1) * COLUMN);  // n concepts sit at width/(n+1) apart
  // Rows leave room for the longest name; the summit for its own name.
  const row = ROW + (Math.max(1, ...concepts.map(concept => labelLines(concept.name).length)) - 1) * LINE;
  const head = TOP + (labelLines(summitName, 36, 2).length - 1) * 18;
  const height = head + top * row + FOOT - row / 2;
  const x: number[] = [];
  const nodes: TrailNode[] = [];
  for (let level = 1; level <= top; level++) {
    const members = concepts.map((_, index) => index).filter(index => levels[index] === level);
    const anchor = (index: number) => {
      const from = (concepts[index].prerequisites ?? []).filter(p => x[p] !== undefined);
      return from.length ? from.reduce((sum, p) => sum + x[p], 0) / from.length : index;
    };
    members.sort((a, b) => level === 1 ? a - b : anchor(a) - anchor(b) || a - b);
    members.forEach((index, position) => {
      x[index] = Math.round(width * (position + 1) / (members.length + 1));
      nodes.push({ index, level, x: x[index], y: height - FOOT - (level - 1) * row });
    });
  }
  return { nodes, width, height, summit: { x: width / 2, y: head - 46 } };
}

/** What to show while one concept is pointed at: it and everything it builds on, and the paths between them. */
export function trailFocus(concepts: TrailConcept[], index: number | null): Set<number> | null {
  return index === null || !concepts[index] ? null : new Set([index, ...trailAncestors(concepts, index)]);
}

/** Where each concept stands. Before planning, only the answers count; after it, the study tasks and their blocks too. */
export function trailStates(concepts: TrailConcept[], understanding: Record<string, string>, planned: boolean,
  study: (index: number) => { done: boolean; scheduled: string | null } | null = () => null): TrailState[] {
  const base = concepts.map((_, index): TrailState => {
    const level = understanding[String(index)];
    if (level === "understood") return "known";
    if (!planned) return level ? "next" : "open";
    const task = study(index);
    if (task?.done) return "done";
    if (task?.scheduled) return "scheduled";
    return "next";
  });
  // A concept still to learn waits while any prerequisite is neither understood nor learned.
  return base.map((state, index) => state === "next" && (concepts[index].prerequisites ?? [])
    .some(p => base[p] !== "known" && base[p] !== "done") ? "locked" : state);
}

/** Every concept that comes before this one, directly or through others. */
export function trailAncestors(concepts: TrailConcept[], index: number): number[] {
  const found = new Set<number>(), stack = [...(concepts[index]?.prerequisites ?? [])];
  while (stack.length) {
    const current = stack.pop()!;
    if (found.has(current) || current < 0 || current >= concepts.length) continue;
    found.add(current); stack.push(...(concepts[current].prerequisites ?? []));
  }
  return [...found].sort((a, b) => a - b);
}

/** The words under the map: what pointing at a concept shows, in learning order, so it never depends on seeing the dimming. */
export function focusSentence(concepts: TrailConcept[], states: TrailState[], index: number | null): string {
  if (index === null || !concepts[index]) return "Arahkan ke satu materi untuk melihat semua yang perlu dipelajari sebelumnya.";
  const before = trailAncestors(concepts, index);
  const name = concepts[index].name;
  if (!before.length) return `${name} tidak butuh prasyarat: bisa langsung dipelajari.`;
  const learned = before.filter(p => states[p] === "known" || states[p] === "done").length;
  const left = before.length - learned;
  return `Sebelum ${name}: ${before.map(p => concepts[p].name).join(" → ")}. ` +
    (left ? `${left} dari ${before.length} masih perlu dipelajari.` : "Semuanya sudah dikuasai.");
}

export function LearningTrail({ concepts, states, summit, dates, anchor, onFocusChange }: {
  concepts: TrailConcept[]; states: TrailState[]; summit: string; dates?: (string | null)[]; anchor: (index: number) => string;
  /** The concept pointed at and its prerequisites, or null; lets the numbered list follow the map. */
  onFocusChange?: (focus: Set<number> | null) => void;
}) {
  const [active, setActive] = useState<number | null>(null);
  if (!concepts.length) return null;
  const { nodes, width, height, summit: peak } = trailLayout(concepts, summit);
  const at = new Map(nodes.map(node => [node.index, node]));
  const dependents = new Set(concepts.flatMap(concept => concept.prerequisites ?? []));
  const focus = trailFocus(concepts, active);
  const point = (index: number | null) => { setActive(index); onFocusChange?.(trailFocus(concepts, index)); };
  const lit = (state: TrailState) => state === "known" || state === "done";
  const lines = concepts.map(concept => labelLines(concept.name));
  // A path leaves the top of the concept below and arrives under the label of the one above, so it never crosses a name.
  const foot = (node: TrailNode) => ({ x: node.x, y: node.y + 38 + (lines[node.index].length - 1) * LINE + (dates?.[node.index] ? 16 : 0) });
  const path = (from: TrailNode, to: { x: number; y: number }) => {
    const start = from.y - 13, middle = (start + to.y) / 2;
    return `M${from.x} ${start} C${from.x} ${middle} ${to.x} ${middle} ${to.x} ${to.y}`;
  };
  const on = (index: number) => focus?.has(index) ? " is-on" : "";
  const known = states.filter(lit).length;
  const summitLines = labelLines(summit, 36, 2);
  return <div className={`trail-graph${focus ? " is-focusing" : ""}`}>
    <div className="trail-scroll">
      <svg className="trail-map" viewBox={`0 0 ${width} ${height}`} role="img" style={{ minWidth: `${Math.round(width * 0.7)}px` }}
        aria-label={`Peta belajar: ${concepts.length} konsep, ${known} sudah dikuasai. Urutan lengkapnya ada di daftar di bawah.`}>
        <path className="trail-mountain" d={`M0 ${height} L${peak.x} ${peak.y + 8} L${width} ${height} Z`} />
        {nodes.flatMap(node => (concepts[node.index].prerequisites ?? []).filter(p => at.has(p)).map(p =>
          <path key={`${p}-${node.index}`} className={`trail-path${lit(states[p]) ? " is-lit" : ""}${focus?.has(p) && focus.has(node.index) ? " is-on" : ""}`}
            d={path(at.get(p)!, foot(node))} />))}
        {nodes.filter(node => !dependents.has(node.index)).map(node =>
          <path key={`summit-${node.index}`} className={`trail-path trail-to-summit${lit(states[node.index]) ? " is-lit" : ""}`} d={path(node, peak)} />)}
        <g className="trail-summit" transform={`translate(${peak.x} ${peak.y})`}>
          <path d="M-14 10 L0 -12 L14 10 Z" />
          <text y={-20 - (summitLines.length - 1) * 18} textAnchor="middle">{summitLines.map((line, row) =>
            <tspan key={row} x="0" dy={row ? 18 : 0}>{line}</tspan>)}</text>
        </g>
        {nodes.map(node => {
          const concept = concepts[node.index], state = states[node.index];
          return <a key={node.index} href={`#${anchor(node.index)}`}
            className={`trail-node is-${state}${concept.kind === "foundation" ? " is-foundation" : ""}${on(node.index)}${active === node.index ? " is-target" : ""}`}
            onPointerEnter={() => point(node.index)} onPointerLeave={() => point(null)} onFocus={() => point(node.index)} onBlur={() => point(null)}>
            <title>{`${node.index + 1}. ${concept.name}: ${STATE_LABEL[state]}${dates?.[node.index] ? `, ${dates[node.index]}` : ""}`}</title>
            <circle cx={node.x} cy={node.y} r="12" />
            {state === "known" || state === "done" ? <path className="trail-check" d={`M${node.x - 5} ${node.y} l3.5 3.5 l6.5 -7`} />
              : <text className="trail-step" x={node.x} y={node.y + 4} textAnchor="middle">{node.index + 1}</text>}
            <text className="trail-label" x={node.x} y={node.y + 30} textAnchor="middle">{lines[node.index].map((line, row) =>
              <tspan key={row} x={node.x} dy={row ? LINE : 0}>{line}</tspan>)}</text>
            {dates?.[node.index] && <text className="trail-date" x={node.x} y={node.y + 46 + (lines[node.index].length - 1) * LINE} textAnchor="middle">{dates[node.index]}</text>}
          </a>;
        })}
      </svg>
    </div>
    <p className="trail-caption" aria-live="polite">{focusSentence(concepts, states, active)}</p>
  </div>;
}
