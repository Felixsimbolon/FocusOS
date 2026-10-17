"use client";
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
import { THEME_KEY as KEY } from "./theme";

export function currentTheme(): Theme {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);
  useEffect(() => { setTheme(currentTheme()); }, []);
  function toggle() {
    const next: Theme = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(KEY, next); } catch { /* The choice still applies to this visit. */ }
    setTheme(next);
  }
  const dark = theme === "dark";
  return <button type="button" className="theme-toggle" onClick={toggle} aria-pressed={dark}
    aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"}>
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {dark ? <><circle cx="12" cy="12" r="4.2" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>
        : <path d="M19.5 14.6A8 8 0 0 1 9.4 4.5a8 8 0 1 0 10.1 10.1Z" />}
    </svg>
  </button>;
}
