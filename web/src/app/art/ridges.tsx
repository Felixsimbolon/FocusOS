/** The horizon: a far volcanic range, a nearer ridge with its own cone, and the near hill
 * that is painted in the page's ground colour, so the landscape becomes the page. */
export const RIDGE_FAR = "M0 300 C120 270 200 250 300 262 C420 276 520 240 640 236 C760 232 860 200 940 176 L962 168 L998 168 L1020 178 C1100 206 1190 236 1300 246 C1360 252 1410 258 1440 262 L1440 420 L0 420 Z";
export const RIDGE_MID = "M0 330 C90 318 170 300 250 262 L300 222 L320 214 L346 214 L368 226 C420 262 500 296 600 306 C720 318 820 296 930 300 C1050 304 1150 324 1260 318 C1340 314 1400 306 1440 304 L1440 420 L0 420 Z";
export const RIDGE_NEAR = "M0 372 C160 352 320 346 480 356 C640 366 780 380 940 370 C1100 360 1260 344 1440 350 L1440 420 L0 420 Z";

export function Ridges() {
  return <g className="ridges">
    <path className="ridge ridge-far" d={RIDGE_FAR} />
    {/* A thin plume above the far cone: the one living detail in the landscape. */}
    <path className="plume" d="M980 160 C972 140 990 128 982 108 C976 92 992 80 986 62" />
    <path className="ridge ridge-mid" d={RIDGE_MID} />
    <path className="ridge ridge-near" d={RIDGE_NEAR} />
  </g>;
}

export function Stars() {
  const points = [[120, 70], [260, 40], [410, 96], [540, 34], [700, 80], [820, 46], [1010, 30], [1180, 64], [1320, 38], [1380, 110], [620, 140], [90, 160]];
  return <g className="stars" aria-hidden="true">{points.map(([x, y], index) =>
    <circle key={index} cx={x} cy={y} r={index % 3 ? 1.4 : 2.1} />)}</g>;
}
