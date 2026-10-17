import { Ridges } from "./ridges";

/** Small drawings for empty moments. Each one shows the place the content will fill. */

export function KiteField() {
  return <svg className="spot" viewBox="0 0 240 140" aria-hidden="true">
    <path className="spot-hill" d="M0 118 C50 98 110 96 150 106 C190 116 220 112 240 104 L240 140 L0 140 Z" />
    <path className="spot-string" d="M70 108 C96 84 120 70 150 40" />
    <g className="spot-kite" transform="translate(150 40) rotate(18)">
      <path d="M0 -22 L14 0 L0 26 L-14 0 Z" /><path className="spot-kite-line" d="M0 -22 L0 26 M-14 0 L14 0" />
    </g>
    <circle className="spot-person" cx="70" cy="104" r="4" />
  </svg>;
}

export function StillWater() {
  return <svg className="spot" viewBox="0 0 240 140" aria-hidden="true">
    <circle className="spot-sun" cx="120" cy="78" r="26" />
    <rect className="spot-sea" x="0" y="80" width="240" height="60" />
    {[92, 104, 116, 128].map((y, index) => <path key={y} className="spot-wave" d={`M${30 + index * 10} ${y} H${210 - index * 10}`} />)}
  </svg>;
}

export function PaperPlane() {
  return <svg className="spot" viewBox="0 0 240 140" aria-hidden="true">
    <path className="spot-trail" d="M20 116 C70 120 90 80 130 84 C160 87 160 60 176 50" />
    <g transform="translate(176 46) rotate(-24)">
      <path className="spot-plane" d="M-26 6 L30 -10 L-8 22 Z" /><path className="spot-plane-fold" d="M30 -10 L-6 10 L-8 22" />
    </g>
  </svg>;
}

export function Constellation({ nodes = 7 }: { nodes?: number }) {
  // A fixed sky of points; how many are lit follows how many entities the graph holds.
  const stars: [number, number][] = [[30, 96], [70, 52], [112, 80], [150, 34], [190, 70], [214, 112], [128, 118], [62, 120], [176, 120]];
  const edges = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [2, 6], [6, 7], [6, 8]];
  const lit = Math.max(2, Math.min(stars.length, nodes));
  return <svg className="spot spot-sky" viewBox="0 0 240 140" aria-hidden="true">
    {edges.filter(([a, b]) => a < lit && b < lit).map(([a, b]) =>
      <line key={`${a}-${b}`} className="spot-edge" x1={stars[a][0]} y1={stars[a][1]} x2={stars[b][0]} y2={stars[b][1]} />)}
    {stars.map(([x, y], index) => <circle key={index} className={index < lit ? "spot-star is-lit" : "spot-star"} cx={x} cy={y} r={index < lit ? 4 : 2} />)}
  </svg>;
}

/** The sign-in view: the whole landscape, with the sun rising once. */
export function Sunrise() {
  return <svg className="sunrise" viewBox="0 0 1440 420" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
    <defs><radialGradient id="sunrise-glow"><stop offset="0%" stopColor="var(--sun)" stopOpacity="0.6" /><stop offset="100%" stopColor="var(--sun)" stopOpacity="0" /></radialGradient></defs>
    <g className="sunrise-sun"><circle cx="720" cy="250" r="120" fill="url(#sunrise-glow)" /><circle className="sun-disc" cx="720" cy="250" r="44" /></g>
    <Ridges />
  </svg>;
}
