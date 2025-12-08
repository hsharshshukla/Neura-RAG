// src/console/pages/Sessions.jsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchJSON } from "../../lib/fetchJSON";

const DEFAULT_LIMIT = 50;

function Pill({ children }) {
  return (
    <span className="px-2 py-0.5 text-xs rounded-full bg-zinc-100 text-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-100">
      {children}
    </span>
  );
}

export default function Sessions() {
  const navigate = useNavigate();

  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // client-side filter by email (backend route doesn't support q yet)
  const [q, setQ] = useState("");

  const load = async (nextLimit = limit) => {
    setLoading(true);
    setErr("");
    try {
      const data = await fetchJSON(`/api/v1/admin/sessions?limit=${nextLimit}`);
      setRows(data?.items || []);
      setTotal(Number(data?.total || 0));
      setLimit(nextLimit);
    } catch (e) {
      setErr(e.message || "Failed to load sessions");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(DEFAULT_LIMIT); /* eslint-disable-next-line */ }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      (r.user_email || "").toLowerCase().includes(needle)
      || String(r.session_id || "").toLowerCase().includes(needle)
    );
  }, [rows, q]);

  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); } catch {}
  };

  const fmtDate = (s) => (s ? new Date(s).toLocaleString() : "—");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">Recent Sessions</h2>
        <div className="flex items-center gap-2">
          <input
            className="border rounded px-3 py-2 w-72"
            placeholder="Filter by user email or session id"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            className="border rounded px-2 py-1 text-sm"
            value={limit}
            onChange={(e) => load(Number(e.target.value))}
            title="Rows to fetch"
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>{n} rows</option>
            ))}
          </select>
          <button
            onClick={() => load(limit)}
            disabled={loading}
            className="px-3 py-2 rounded border disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}

      <div className="overflow-auto border rounded">
        <table className="min-w-[980px] w-full">
          <thead>
            <tr className="text-left text-sm text-gray-600">
              <th className="p-2">Session ID</th>
              <th className="p-2">User</th>
              <th className="p-2">Created</th>
              <th className="p-2">Messages</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id ?? s.session_id} className="border-t">
                <td className="p-2 font-mono text-xs">
                  {s.session_id || "—"}
                  {s.session_id && (
                    <button
                      className="ml-2 text-xs text-gray-600 hover:underline"
                      onClick={() => copy(String(s.session_id))}
                      title="Copy session id"
                    >
                      Copy
                    </button>
                  )}
                </td>
                <td className="p-2">
                  <div className="flex items-center gap-2">
                    <span>{s.user_email || "—"}</span>
                    {s.user_email && <Pill>User</Pill>}
                    {s.user_email && (
                      <button
                        className="text-xs text-gray-600 hover:underline"
                        onClick={() => copy(String(s.user_email))}
                        title="Copy email"
                      >
                        Copy
                      </button>
                    )}
                  </div>
                </td>
                <td className="p-2">{fmtDate(s.created_at)}</td>
                <td className="p-2">{s.message_count ?? 0}</td>
                <td className="p-2">
                  {s.session_id ? (
                    <button
                      // onClick={() => navigate(`/chat/${encodeURIComponent(s.session_id)}`)}
                      onClick={() => navigate(`/console/sessions/${encodeURIComponent(s.session_id)}`)}
                      className="px-2 py-1 text-sm rounded border hover:bg-zinc-50"
                      title="Open chat"
                    >
                      Open
                    </button>
                  ) : (
                    <span className="text-sm text-gray-400">—</span>
                  )}
                </td>
              </tr>
            ))}
            {!filtered.length && !loading && (
              <tr>
                <td colSpan={5} className="p-4 text-sm text-gray-500">
                  {rows.length ? "No matches for your filter." : "No sessions found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-gray-500">
        Showing {filtered.length || 0} of {total || rows.length} fetched (limit {limit})
      </div>
    </div>
  );
}
