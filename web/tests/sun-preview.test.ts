import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { dayWindow, dewy, heldSun, minutesAt, phase, previewRange, xAt } from "../src/app/hud/focus-hud";
import { Dew, Mist, Ridges, Stars } from "../src/app/art/ridges";

const hours = { days: [1, 2, 3, 4, 5], start_minute: 540, end_minute: 1020 };
const day = dayWindow({ kind: "during", progress: 0.5, minutesLeft: 240 }, hours);

describe("dragging the sun", () => {
  it("maps the arc to the working window and the ground past it to four more hours", () => {
    expect(minutesAt(190, day)).toBe(540);
    expect(minutesAt(1250, day)).toBe(1020);
    expect(minutesAt(720, day)).toBe(780);
    expect(minutesAt(0, day)).toBe(300);
    expect(minutesAt(1440, day)).toBe(1260);
    expect(minutesAt(-500, day)).toBe(300);
  });

  it("reaches dawn at one end and night at the other", () => {
    const [low, high] = previewRange(day);
    expect(phase(low)).toBe("night");
    expect(phase(low + 60)).toBe("dawn");
    expect(phase(high)).toBe("night");
    expect(dewy(low + 60)).toBe(true);
    expect(dewy(780)).toBe(false);
  });

  it("finds a time's position again from its minutes", () => {
    for (const minutes of [300, 420, 540, 780, 1020, 1140, 1260]) expect(minutesAt(xAt(minutes, day), day)).toBe(minutes);
  });

  it("lets the held sun sink outside the window but never out of reach", () => {
    expect(heldSun(780, day)).toEqual({ t: 0.5, sink: 0 });
    expect(heldSun(1260, day)).toEqual({ t: 1, sink: 30 });
    expect(heldSun(300, day).sink).toBeLessThanOrEqual(30);
  });

  it("uses 06:00 to 18:00 on a rest day", () => {
    expect(dayWindow({ kind: "rest" }, hours)).toEqual({ start: 360, end: 1080 });
  });
});

describe("the landscape's morning and night", () => {
  it("draws the stars, mist and dew so they can fade in by the hour", () => {
    const markup = renderToStaticMarkup(React.createElement("svg", null,
      React.createElement(Stars), React.createElement(Ridges, { valley: React.createElement(Mist) }), React.createElement(Dew)));
    expect(markup).toContain('class="stars"');
    expect(markup).toContain('class="dew"');
    // The mist lies between the middle ridge and the near hill.
    expect(markup.indexOf('class="mist"')).toBeGreaterThan(markup.indexOf("ridge-mid"));
    expect(markup.indexOf('class="mist"')).toBeLessThan(markup.indexOf("ridge-near"));
  });
});
