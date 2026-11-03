import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { focusSentence, labelLines, LearningTrail, trailAncestors, trailFocus, trailLayout, trailLevels, trailStates, type TrailConcept } from "../src/app/projects/learning-trail";
import { answersFor, studyFinder, type Analysis } from "../src/app/projects/assignment-flow";
import { POST as ASSIGNMENT_POST } from "../src/app/api/assignments/[[...path]]/route";
import { getServerAccessToken } from "../src/server/auth/session";
vi.mock("server-only", () => ({}));
vi.mock("next/server", async original => ({ ...(await original<typeof import("next/server")>()), after: vi.fn() }));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: () => "https://api.example.test" }));
vi.mock("../src/server/jobs", () => ({ runBackgroundJob: vi.fn() }));

const id = "11111111-1111-4111-8111-111111111111";
// Statistik deskriptif -> Korelasi -> Regresi, and Visualisasi from Statistik deskriptif.
const path: TrailConcept[] = [{ name: "Statistik deskriptif", kind: "foundation" }, { name: "Korelasi", prerequisites: [0] },
  { name: "Regresi", prerequisites: [1] }, { name: "Visualisasi", prerequisites: [0] }];
const analysis = { title: "Tugas 2", summary: "", project_name: "Stat", deliverables: [], due: { raw_text: null, date: null, time: null },
  concepts: path.map(item => ({ ...item, why: "x", study_minutes: 60 })), subtasks: [] } as Analysis;

beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal("React", React);
  vi.mocked(getServerAccessToken).mockResolvedValue("server-session");
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ id })));
});

describe("learning trail", () => {
  it("climbs from foundations at the foot to the summit", () => {
    expect(trailLevels(path)).toEqual([1, 2, 3, 2]);
    expect(trailAncestors(path, 2)).toEqual([0, 1]);
    const { nodes, summit } = trailLayout(path);
    const y = (index: number) => nodes.find(node => node.index === index)!.y;
    expect(y(0)).toBeGreaterThan(y(1));
    expect(y(1)).toBeGreaterThan(y(2));
    expect(y(1)).toBe(y(3));
    expect(summit.y).toBeLessThan(y(2));
  });
  it("tolerates a reference to a missing concept or a loop from an old or edited analysis", () => {
    expect(trailLevels([{ name: "A", prerequisites: [5] }, { name: "B", prerequisites: [1] }])).toEqual([1, 1]);
  });
  it("locks a concept until what it builds on is understood or learned", () => {
    expect(trailStates(path, { "0": "not", "1": "understood" }, false)).toEqual(["next", "known", "open", "open"]);
    const study = (index: number) => index === 0 ? { done: true, scheduled: null } : index === 1 ? { done: false, scheduled: "Wed 21 Oct, 14:00" } : null;
    expect(trailStates(path, { "0": "not", "1": "not", "2": "not", "3": "partly" }, true, study)).toEqual(["done", "scheduled", "locked", "next"]);
  });
  it("draws every concept as a link to its place in the numbered list", () => {
    const html = renderToStaticMarkup(React.createElement(LearningTrail, { concepts: path, states: ["known", "next", "locked", "next"], summit: "Tugas 2",
      anchor: (index: number) => `concept-${index}`, dates: [null, "Wed 21 Oct, 14:00", null, null] }));
    expect(html.match(/class="trail-node/g)).toHaveLength(4);
    expect(html).toContain('href="#concept-2"');
    expect(html).toContain("is-foundation");
    expect(html).toContain("Wed 21 Oct, 14:00");
    expect(html).toContain("Tugas 2");
    // Three prerequisite paths, and two concepts lead straight to the summit.
    expect(html.match(/class="trail-path/g)).toHaveLength(5);
  });
});

describe("seeing the whole path", () => {
  it("shows whole names on up to three lines instead of cutting them", () => {
    expect(labelLines("Uji asumsi klasik regresi linear berganda")).toEqual(["Uji asumsi klasik", "regresi linear", "berganda"]);
    expect(labelLines("Korelasi")).toEqual(["Korelasi"]);
    const long = labelLines("satu dua tiga empat lima enam tujuh delapan sembilan sepuluh sebelas duabelas", 12);
    expect(long).toHaveLength(3);
    expect(long[2].endsWith("…")).toBe(true);
  });
  it("widens a crowded row instead of piling names on each other, and leaves room for long names", () => {
    const wide: TrailConcept[] = Array.from({ length: 8 }, (_, index) => ({ name: `Dasar ${index}` }));
    const { nodes, width } = trailLayout(wide);
    expect(width).toBeGreaterThanOrEqual(8 * 160);
    const xs = nodes.map(node => node.x).sort((a, b) => a - b);
    expect(Math.min(...xs.slice(1).map((x, index) => x - xs[index]))).toBeGreaterThanOrEqual(150);
    const short = trailLayout(path), tall = trailLayout(path.map(item => ({ ...item, name: `${item.name} untuk analisis data penjualan` })));
    expect(tall.height).toBeGreaterThan(short.height);
  });
  it("pointing at a concept lights it and everything it builds on, directly or through others", () => {
    expect(trailFocus(path, 2)).toEqual(new Set([2, 1, 0]));
    expect(trailFocus(path, 0)).toEqual(new Set([0]));
    expect(trailFocus(path, null)).toBeNull();
    expect(focusSentence(path, ["known", "next", "locked", "next"], 2)).toBe("Sebelum Regresi: Statistik deskriptif → Korelasi. 1 dari 2 masih perlu dipelajari.");
    expect(focusSentence(path, ["known", "next", "locked", "next"], 0)).toBe("Statistik deskriptif tidak butuh prasyarat: bisa langsung dipelajari.");
    expect(focusSentence(path, ["known", "done", "next", "next"], 2)).toContain("Semuanya sudah dikuasai.");
  });
  it("draws the map at every width, with whole names and the caption", () => {
    const html = renderToStaticMarkup(React.createElement(LearningTrail, { concepts: [{ name: "Uji asumsi klasik regresi linear berganda" }],
      states: ["next"], summit: "Tugas 2", anchor: (index: number) => `concept-${index}` }));
    expect(html).toContain("<tspan");
    expect(html).toContain("berganda");
    expect(html).toContain('class="trail-caption"');
    expect(html).toContain("Arahkan ke satu materi");
  });
});

describe("assignment flow on the trail", () => {
  it("answering that you understand a concept also answers what it builds on", () => {
    expect(answersFor(analysis, { "0": "not" }, 2, "understood")).toEqual({ "2": "understood", "1": "understood" });
    expect(answersFor(analysis, {}, 2, "partly")).toEqual({ "2": "partly" });
  });
  it("finds a concept's study task and its first block by title", () => {
    const find = studyFinder(analysis, [{ title: "[Stat] Belajar: Korelasi", status: "done" }],
      [{ title: "[Stat] Belajar: Regresi", start: "2026-10-22T07:00:00Z", timezone: "Asia/Jakarta" },
       { title: "[Stat] Belajar: Regresi", start: "2026-10-21T07:00:00Z", timezone: "Asia/Jakarta" }]);
    expect(find(1)).toEqual({ done: true, scheduled: null });
    expect(find(2)?.scheduled).toContain("21");
    expect(find(3)).toBeNull();
  });
  it("validates prerequisite removals before forwarding them", async () => {
    const send = (body: unknown) => ASSIGNMENT_POST(new NextRequest("http://localhost", { method: "POST", body: JSON.stringify(body) }),
      { params: Promise.resolve({ path: [id, "graph"] }) });
    expect((await send({ expected_version: 2, concept: 2, remove_prerequisite: 1 })).status).toBe(200);
    expect(JSON.parse(vi.mocked(fetch).mock.calls.at(-1)![1]!.body as string)).toEqual({ expected_version: 2, concept: 2, remove_prerequisite: 1 });
    for (const bad of [{ expected_version: 2, concept: 12, remove_prerequisite: 1 }, { expected_version: 2, concept: 1 },
      { expected_version: 2, concept: 1, remove_prerequisite: 0, owner: "x" }])
      expect((await send(bad)).status).toBe(400);
  });
});
