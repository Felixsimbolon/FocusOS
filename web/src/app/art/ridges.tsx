import type { ReactNode } from "react";

/** The horizon: a far volcanic range, a nearer ridge with its own cone, and the near hill
 * that is painted in the page's ground colour, so the landscape becomes the page. */
export const RIDGE_FAR = "M0 300 C120 270 200 250 300 262 C420 276 520 240 640 236 C760 232 860 200 940 176 L962 168 L998 168 L1020 178 C1100 206 1190 236 1300 246 C1360 252 1410 258 1440 262 L1440 420 L0 420 Z";
export const RIDGE_MID = "M0 330 C90 318 170 300 250 262 L300 222 L320 214 L346 214 L368 226 C420 262 500 296 600 306 C720 318 820 296 930 300 C1050 304 1150 324 1260 318 C1340 314 1400 306 1440 304 L1440 420 L0 420 Z";
export const RIDGE_NEAR = "M0 372 C160 352 320 346 480 356 C640 366 780 380 940 370 C1100 360 1260 344 1440 350 L1440 420 L0 420 Z";

/** `valley` is drawn between the middle ridge and the near hill, where morning mist lies. */
export function Ridges({ valley }: { valley?: ReactNode }) {
  return <g className="ridges">
    <path className="ridge ridge-far" d={RIDGE_FAR} />
    {/* A thin plume above the far cone: the one living detail in the landscape. */}
    <path className="plume" d="M980 160 C972 140 990 128 982 108 C976 92 992 80 986 62" />
    <path className="ridge ridge-mid" d={RIDGE_MID} />
    {valley}
    <path className="ridge ridge-near" d={RIDGE_NEAR} />
  </g>;
}

export function Stars() {
  const points = [[120, 70], [260, 40], [410, 96], [540, 34], [700, 80], [820, 46], [1010, 30], [1180, 64], [1320, 38], [1380, 110], [620, 140], [90, 160],
    [190, 118], [340, 22], [470, 150], [760, 126], [900, 98], [1090, 120], [1250, 150], [1420, 70], [40, 40], [1130, 18]];
  return <g className="stars" aria-hidden="true">{points.map(([x, y], index) =>
    <circle key={index} cx={x} cy={y} r={index % 3 ? 1.4 : 2.1} style={{ animationDelay: `${(index * 0.37) % 3}s` }} />)}</g>;
}

/** Morning mist in the valley: soft banks that sit on the middle ridge's foot. */
export function Mist() {
  const banks = [[260, 318, 300, 22], [700, 326, 360, 20], [1180, 330, 320, 24]];
  return <g className="mist" aria-hidden="true">{banks.map(([cx, cy, rx, ry], index) =>
    <ellipse key={index} cx={cx} cy={cy} rx={rx} ry={ry} fill="url(#mist-bank)" />)}</g>;
}

/** Dew on the near hill: drops just below its edge, a few of them catching the light. */
export function Dew() {
  // x, and how far below the hill's edge (the edge's height at x is listed alongside).
  const drops: [number, number][] = [[140, 357.8 + 9], [230, 353.2 + 20], [310, 351.3 + 7], [395, 352.2 + 26], [470, 355.3 + 12], [560, 361.5 + 22],
    [650, 367.5 + 8], [720, 371 + 24], [800, 373.3 + 11], [880, 372.7 + 27], [960, 368.5 + 9], [1040, 363.5 + 19], [1120, 357.7 + 8],
    [1200, 353.3 + 24], [1290, 349.5 + 11], [1370, 348.7 + 22]];
  return <g className="dew" aria-hidden="true">{drops.map(([x, y], index) =>
    <g key={index} transform={`translate(${x} ${y})`}>
      <circle className="dew-drop" r={index % 4 ? 2.6 : 3.4} />
      <circle className="dew-shine" r="0.9" cx="-0.9" cy="-0.9" />
      {index % 3 === 0 && <path className="dew-glint" d="M0 -9 L1.1 -1.1 L9 0 L1.1 1.1 L0 9 L-1.1 1.1 L-9 0 L-1.1 -1.1 Z"
        style={{ animationDelay: `${(index * 0.53) % 2.4}s` }} />}
    </g>)}</g>;
}
