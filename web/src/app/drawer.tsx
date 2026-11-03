"use client";
import { useState, type ReactNode } from "react";

/** A collapsible section whose panel mounts the first time it opens, so closed drawers fetch nothing when Home loads.
 *  It stays mounted after closing, keeping what was loaded and typed. */
export function Drawer({ id, title, hint, children }: { id: string; title: string; hint: string; children: ReactNode }) {
  const [opened, setOpened] = useState(false);
  return <details id={id} className="drawer" onToggle={event => { if (event.currentTarget.open) setOpened(true); }}>
    <summary><span>{title}</span><small>{hint}</small></summary>
    <div className="drawer-body">{opened ? children : null}</div>
  </details>;
}
