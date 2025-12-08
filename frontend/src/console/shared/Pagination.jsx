// src/console/shared/Pagination.jsx
import { useMemo } from "react";

export default function Pagination({
  total = 0,
  limit = 20,
  offset = 0,
  onPageChange,
}) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  const canPrev = page > 1;
  const canNext = page < pages;

  const jump = (p) => {
    const clamped = Math.min(Math.max(1, p), pages);
    const newOffset = (clamped - 1) * limit;
    onPageChange?.(clamped, newOffset);
  };

  const label = useMemo(() => {
    const start = total === 0 ? 0 : offset + 1;
    const end = Math.min(offset + limit, total);
    return `${start}–${end} of ${total}`;
  }, [total, offset, limit]);

  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <div className="text-gray-500">{label}</div>
      <div className="flex items-center gap-1">
        <button
          className="px-2 py-1 border rounded disabled:opacity-50"
          onClick={() => jump(1)}
          disabled={!canPrev}
          title="First"
        >
          «
        </button>
        <button
          className="px-2 py-1 border rounded disabled:opacity-50"
          onClick={() => jump(page - 1)}
          disabled={!canPrev}
          title="Previous"
        >
          ‹
        </button>
        <span className="px-2">
          Page <span className="font-medium">{page}</span> / {pages}
        </span>
        <button
          className="px-2 py-1 border rounded disabled:opacity-50"
          onClick={() => jump(page + 1)}
          disabled={!canNext}
          title="Next"
        >
          ›
        </button>
        <button
          className="px-2 py-1 border rounded disabled:opacity-50"
          onClick={() => jump(pages)}
          disabled={!canNext}
          title="Last"
        >
          »
        </button>
      </div>
    </div>
  );
}
