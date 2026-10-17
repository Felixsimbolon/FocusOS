import type { MetadataRoute } from "next";

/** Lets FocusOS be installed on a phone or desktop and open in its own window. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "FocusOS",
    short_name: "FocusOS",
    description: "Say what is on your mind; FocusOS saves the work and finds time for it.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#eef2ef",
    theme_color: "#8ec1e3",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
  };
}
