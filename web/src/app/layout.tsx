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
      <body>{children}<ServiceWorker /></body>
    </html>
  );
}
