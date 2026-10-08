"use client";
import { useState, type ReactNode } from "react";

export function PaginatedItems({ items, pageSize = 4, label, className, as = "div" }: {
  items: ReactNode[]; pageSize?: number; label: string; className?: string; as?: "div" | "ul";
}) {
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  const current = Math.min(page, pages);
  const start = (current - 1) * pageSize;
  const Container = as;
  return <div className="paged-content">
    <Container className={className}>{items.slice(start, start + pageSize)}</Container>
    {pages > 1 && <nav className="list-pagination" aria-label={label}>
      <span aria-live="polite">{start + 1}-{Math.min(start + pageSize, items.length)} of {items.length}</span>
      <div><button type="button" disabled={current === 1} onClick={() => setPage(current - 1)} aria-label={`Previous ${label}`}>Previous</button>
        <span>Page {current} / {pages}</span>
        <button type="button" disabled={current === pages} onClick={() => setPage(current + 1)} aria-label={`Next ${label}`}>Next</button></div>
    </nav>}
  </div>;
}
