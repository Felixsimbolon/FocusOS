/** An assignment's learning path drawn as a trail up a mountain: foundations at the foot, the assignment at the summit,
 * each path a prerequisite. The numbered list beside it is the same path in learning order, and the one screen readers use. */

export type TrailConcept = { name: string; kind?: "core" | "foundation"; prerequisites?: number[] };
export type TrailState = "known" | "done" | "scheduled" | "next" | "locked" | "open";
export type TrailNode = { index: number; level: number; x: number; y: number };

const WIDTH = 720, ROW = 92, TOP = 86, FOOT = 64;

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

/** Rows bottom-up by level; within a row, a concept sits near the prerequisites it climbs from, to keep paths from crossing. */
export function trailLayout(concepts: TrailConcept[]): { nodes: TrailNode[]; height: number; summit: { x: number; y: number } } {
  const levels = trailLevels(concepts), top = Math.max(1, ...levels);
  const height = TOP + top * ROW + FOOT - ROW / 2;
  const x: number[] = [];
  const nodes: TrailNode[] = [];
  for (let level = 1; level <= top; level++) {
    const row = concepts.map((_, index) => index).filter(index => levels[index] === level);
    const anchor = (index: number) => {
      const from = (concepts[index].prerequisites ?? []).filter(p => x[p] !== undefined);
      return from.length ? from.reduce((sum, p) => sum + x[p], 0) / from.length : index;
    };
    row.sort((a, b) => level === 1 ? a - b : anchor(a) - anchor(b) || a - b);
    row.forEach((index, position) => {
      x[index] = Math.round(WIDTH * (position + 1) / (row.length + 1));
      nodes.push({ index, level, x: x[index], y: height - FOOT - (level - 1) * ROW });
    });
  }
  return { nodes, height, summit: { x: WIDTH / 2, y: TOP - 46 } };
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

function short(text: string, length = 24) {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

export function LearningTrail({ concepts, states, summit, dates, anchor }: {
  concepts: TrailConcept[]; states: TrailState[]; summit: string; dates?: (string | null)[]; anchor: (index: number) => string;
}) {
  if (!concepts.length) return null;
  const { nodes, height, summit: peak } = trailLayout(concepts);
  const at = new Map(nodes.map(node => [node.index, node]));
  const dependents = new Set(concepts.flatMap(concept => concept.prerequisites ?? []));
  const lit = (state: TrailState) => state === "known" || state === "done";
  // A path leaves the top of the concept below and arrives under the label of the one above, so it never crosses a name.
  const foot = (node: TrailNode) => ({ x: node.x, y: node.y + (dates?.[node.index] ? 54 : 38) });
  const path = (from: TrailNode, to: { x: number; y: number }) => {
    const start = from.y - 13, middle = (start + to.y) / 2;
    return `M${from.x} ${start} C${from.x} ${middle} ${to.x} ${middle} ${to.x} ${to.y}`;
  };
  const known = states.filter(lit).length;
  return <svg className="trail-map" viewBox={`0 0 ${WIDTH} ${height}`} role="img"
    aria-label={`Peta belajar: ${concepts.length} konsep, ${known} sudah dikuasai. Urutan lengkapnya ada di daftar di bawah.`}>
    <path className="trail-mountain" d={`M0 ${height} L${peak.x} ${peak.y + 8} L${WIDTH} ${height} Z`} />
    {nodes.flatMap(node => (concepts[node.index].prerequisites ?? []).filter(p => at.has(p)).map(p =>
      <path key={`${p}-${node.index}`} className={`trail-path${lit(states[p]) ? " is-lit" : ""}`} d={path(at.get(p)!, foot(node))} />))}
    {nodes.filter(node => !dependents.has(node.index)).map(node =>
      <path key={`summit-${node.index}`} className={`trail-path trail-to-summit${lit(states[node.index]) ? " is-lit" : ""}`} d={path(node, peak)} />)}
    <g className="trail-summit" transform={`translate(${peak.x} ${peak.y})`}>
      <path d="M-14 10 L0 -12 L14 10 Z" /><text y="-20" textAnchor="middle">{short(summit, 40)}</text>
    </g>
    {nodes.map(node => {
      const concept = concepts[node.index], state = states[node.index];
      return <a key={node.index} href={`#${anchor(node.index)}`} className={`trail-node is-${state}${concept.kind === "foundation" ? " is-foundation" : ""}`}>
        <title>{`${node.index + 1}. ${concept.name}: ${STATE_LABEL[state]}${dates?.[node.index] ? `, ${dates[node.index]}` : ""}`}</title>
        <circle cx={node.x} cy={node.y} r="12" />
        {state === "known" || state === "done" ? <path className="trail-check" d={`M${node.x - 5} ${node.y} l3.5 3.5 l6.5 -7`} />
          : <text className="trail-step" x={node.x} y={node.y + 4} textAnchor="middle">{node.index + 1}</text>}
        <text className="trail-label" x={node.x} y={node.y + 30} textAnchor="middle">{short(concept.name)}</text>
        {dates?.[node.index] && <text className="trail-date" x={node.x} y={node.y + 46} textAnchor="middle">{dates[node.index]}</text>}
      </a>;
    })}
  </svg>;
}
