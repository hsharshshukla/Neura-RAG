// src/console/pages/Files.jsx
import { useEffect, useMemo, useState } from "react";
import { fetchJSON } from "../../lib/fetchJSON";
import Pagination from "../shared/Pagination";

const DEFAULT_LIMIT = 20;

const possibleTypes = [
  "",          // All
  "pdf",
  "docx",
  "pptx",
  "txt",
  "md",
  "csv",
  "xlsx",
  "html",
  "image",
];

function Stat({ k, v }) {
  return (
    <div className="rounded-lg border p-3 bg-white dark:bg-zinc-900">
      <div className="text-xs text-zinc-500">{k}</div>
      <div className="text-sm font-medium mt-0.5">{String(v ?? "—")}</div>
    </div>
  );
}

export default function Files() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [offset, setOffset] = useState(0);

  const [q, setQ] = useState("");
  const [type, setType] = useState("");

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [stats, setStats] = useState({});

  const safeNumber = (v, fallback = 0) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
    };

  const load = async (opts = {}) => {
    const nextOffset = opts.nextOffset ?? offset;
    const nextLimit  = opts.nextLimit  ?? limit;
    const nextQ      = opts.search     ?? q;
    const nextType   = opts.type       ?? type;

    setLoading(true);
    setErr("");
    try {
      const params = new URLSearchParams();
      if (nextQ) params.set("q", nextQ);
      if (nextType) params.set("type", nextType);
      params.set("limit", String(nextLimit));
      params.set("offset", String(nextOffset));

      const data = await fetchJSON(`/api/v1/admin/uploads?${params.toString()}`);

      // Defensive shaping to avoid UI crashes if backend shape changes or 500s
      const items = Array.isArray(data?.items) ? data.items : [];
      setRows(items);
      setTotal(safeNumber(data?.total, items.length));
      setOffset(nextOffset);
      setLimit(nextLimit);

      const s = data?.stats && typeof data.stats === "object" ? data.stats : {};
      setStats(s);
    } catch (e) {
      setErr(e?.message || "Failed to load uploads");
      setRows([]);
      setTotal(0);
      setStats({});
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load({ nextOffset: 0 }); /* eslint-disable-line */ }, []);

  const onSearch = () => load({ search: q, type, nextOffset: 0 });
  const onSearchKey = (e) => (e.key === "Enter" ? onSearch() : null);
  const onTypeChange = (val) => {
    setType(val);
    load({ type: val, search: q, nextOffset: 0 });
  };
  const onPageChange = (_page, newOffset) => load({ nextOffset: newOffset });

  const countText = useMemo(
    () => (rows.length ? `${rows.length} row${rows.length > 1 ? "s" : ""}` : "—"),
    [rows.length]
  );
  const fmtDate = (s) => (s ? new Date(s).toLocaleString() : "—");
  const fmtBytes = (n) => {
    if (n == null || isNaN(n)) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0, v = Number(n);
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Files</h2>

      {/* Vector store stats (defensive – tolerate missing keys) */}
      <div className="rounded-xl border p-4 bg-white dark:bg-zinc-900">
        <div className="text-sm text-zinc-500 mb-3">Vector Store</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Stat k="Chunks" v={stats?.Chunks ?? stats?.chunks} />
          <Stat k="Storage" v={stats?.Storage ?? stats?.storage} />
          <Stat k="Last Reindex" v={stats?.["Last Reindex"] ?? stats?.last_reindex} />
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <input
            className="border rounded px-3 py-2 w-72"
            placeholder="Search filename"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onSearchKey}
          />
          <button onClick={onSearch} className="px-3 py-2 rounded border" disabled={loading}>
            Search
          </button>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="border rounded px-2 py-1 text-sm"
            title="Filter by type"
            value={type}
            onChange={(e) => onTypeChange(e.target.value)}
          >
            {possibleTypes.map((t) => (
              <option key={t || "all"} value={t}>
                {t ? t.toUpperCase() : "All types"}
              </option>
            ))}
          </select>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={limit}
            onChange={(e) => load({ nextLimit: Number(e.target.value), nextOffset: 0 })}
            title="Rows per page"
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>{n} / page</option>
            ))}
          </select>
          <button onClick={() => load({ nextOffset: offset })} className="px-3 py-2 rounded border" disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}

      {/* Table */}
      <div className="overflow-auto border rounded">
        <table className="min-w-[1100px] w-full">
          <thead>
            <tr className="text-left text-sm text-gray-600">
              <th className="p-2">Filename</th>
              <th className="p-2">Type</th>
              <th className="p-2">Size</th>
              <th className="p-2">Owner</th>
              <th className="p-2">Created</th>
              <th className="p-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u, idx) => {
              // Accept multiple possible shapes to avoid runtime errors
              const filename = u.filename || u.name || u.original_name || "—";
              const filetype = u.filetype || u.type || u.ext || "—";
              const size     = u.size_bytes ?? u.size ?? u.bytes;
              const owner    = u.user_email || u.owner_email || u.userId || u.user_id || "—";
              const created  = u.created_at || u.createdAt || u.inserted_at;
              const status   = u.status || u.processing_state || u.state || "—";

              const key = u.id ?? `${filename}-${created ?? idx}`;

              return (
                <tr key={key} className="border-t">
                  <td className="p-2 font-medium break-all">{filename}</td>
                  <td className="p-2">{String(filetype)}</td>
                  <td className="p-2">{fmtBytes(size)}</td>
                  <td className="p-2">{owner}</td>
                  <td className="p-2">{fmtDate(created)}</td>
                  <td className="p-2">{status}</td>
                </tr>
              );
            })}
            {!rows.length && !loading && (
              <tr>
                <td className="p-4 text-sm text-gray-500" colSpan={6}>
                  No files found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination total={total} limit={limit} offset={offset} onPageChange={onPageChange} />

      <div className="text-xs text-zinc-500">{countText}</div>
    </div>
  );
}
