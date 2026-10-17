"use client";
import { useEffect } from "react";

/** Registers the service worker in production so FocusOS can be installed and shows an offline page. */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => { /* The app works without it. */ });
  }, []);
  return null;
}
