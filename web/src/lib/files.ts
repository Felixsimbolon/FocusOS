/** What a project can keep: the same files the composer and assignments read. */
export const MAX_FILE_BYTES = 3_000_000;
export const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export const FILE_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp", DOCX, "text/markdown", "text/plain"];
/** For a file picker's accept attribute: extensions too, since browsers often give .md no type. */
export const FILE_ACCEPT = ".pdf,.docx,.md,.markdown,.txt,image/png,image/jpeg,image/webp";
export const FILE_KINDS = "PDF, Word (.docx), Markdown, text, PNG, JPEG or WebP";

const BY_EXTENSION: Record<string, string> = { pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
  webp: "image/webp", docx: DOCX, md: "text/markdown", markdown: "text/markdown", txt: "text/plain" };

/** The type FocusOS reads a file as, or null. Browsers often send .md as "" or text/x-markdown, so the name decides then. */
export function fileType(file: { name: string; type: string }): string | null {
  const type = file.type.split(";")[0].trim().toLowerCase();
  if (FILE_TYPES.includes(type)) return type;
  const extension = file.name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] ?? "";
  const named = BY_EXTENSION[extension] ?? null;
  // A name only fills in a missing or generic type; it never overrides a different, specific one.
  return named && (!type || type === "application/octet-stream" || type.startsWith("text/")) ? named : null;
}
