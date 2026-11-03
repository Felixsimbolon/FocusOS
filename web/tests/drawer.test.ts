import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Drawer } from "../src/app/drawer";

beforeEach(() => vi.stubGlobal("React", React));
describe("Home drawers", () => {
  it("render their heading but leave the panel unmounted until opened, so nothing is fetched on load", () => {
    let rendered = false;
    const Panel = () => { rendered = true; return React.createElement("p", null, "panel"); };
    const html = renderToStaticMarkup(React.createElement(Drawer, { id: "usage", title: "AI usage", hint: "The last seven days" }, React.createElement(Panel)));
    expect(html).toContain('id="usage"');
    expect(html).toContain("<span>AI usage</span><small>The last seven days</small>");
    expect(html).toContain('<div class="drawer-body"></div>');
    expect(rendered).toBe(false);
  });
});
