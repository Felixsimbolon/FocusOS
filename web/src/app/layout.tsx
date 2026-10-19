import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Newsreader } from "next/font/google";
import "./globals.css";
import { THEME_SCRIPT } from "./theme";
import { ServiceWorker } from "./service-worker";

// Self-hosted at build time; the browser never requests Google Fonts.
const ui = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-ui", axes: ["wdth", "opsz"] });
const prose = Newsreader({ subsets: ["latin"], variable: "--font-prose", style: ["normal", "italic"], axes: ["opsz"] });

export const metadata: Metadata = {
  title: "FocusOS",
  appleWebApp: { capable: true, title: "FocusOS", statusBarStyle: "default" },
  description: "Say what is on your mind; FocusOS saves the work, answers from your notes and finds time for it.",
};

export const viewport: Viewport = { themeColor: "#eef2ef" };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${ui.variable} ${prose.variable}`} data-phase="day" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body>
        {/* Shared ridge fills, referenced from globals.css so every landscape uses the same haze. */}
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id="ridge-far-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" className="ridge-stop ridge-far-top" /><stop offset="1" className="ridge-stop ridge-far-foot" />
            </linearGradient>
            <linearGradient id="ridge-mid-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" className="ridge-stop ridge-mid-top" /><stop offset="1" className="ridge-stop ridge-mid-foot" />
            </linearGradient>
          </defs>
        </svg>
        {children}<ServiceWorker />
      </body>
    </html>
  );
}
