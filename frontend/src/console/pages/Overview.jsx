// src/console/pages/Overview.jsx
import { useEffect, useState } from "react";
import { fetchJSON } from "../../lib/fetchJSON";
import StatCard from "../shared/StatCard";
import Bar from "../shared/Bar";

export default function Overview() {
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState("…");
  const [totals, setTotals] = useState({ users: 0, documents: 0, chat_sessions: 0 });
  const [metrics, setMetrics] = useState({
    active_users_24h: 0,
    uploads_24h: 0,
    queries_24h: 0,
    total_users: 0,
    tiers: { free: 0, mini: 0, pro: 0 },
    free_to_pro: 0,
  });
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const [h, o, m] = await Promise.all([
        fetchJSON("/api/v1/admin/health").catch(() => ({ status: "down" })),
        fetchJSON("/api/v1/admin/overview"),
        fetchJSON("/api/v1/admin/metrics"),
      ]);
      setHealth(h?.status === "ok" ? "OK" : "Down");
      setTotals(o?.totals || { users: 0, documents: 0, chat_sessions: 0 });
      setMetrics(
        m || {
          active_users_24h: 0,
          uploads_24h: 0,
          queries_24h: 0,
          total_users: 0,
          tiers: { free: 0, mini: 0, pro: 0 },
          free_to_pro: 0,
        }
      );
    } catch (e) {
      setErr(e?.message || "Failed to load overview");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const tiers = metrics.tiers || { free: 0, mini: 0, pro: 0 };
  const maxTier = Math.max(tiers.free, tiers.mini, tiers.pro, 1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Overview</h2>
        <div
          className={`text-sm px-2 py-1 rounded ${
            health === "OK"
              ? "bg-emerald-100 text-emerald-700"
              : "bg-red-100 text-red-700"
          }`}
        >
          Health: {health}
        </div>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}

      {/* Totals */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Total Users" value={totals.users} />
        <StatCard label="Documents" value={totals.documents} />
        <StatCard label="Chat Sessions" value={totals.chat_sessions} />
      </div>

      {/* 24h activity */}
      <div className="rounded-xl border p-4 bg-white dark:bg-zinc-900">
        <div className="text-sm text-zinc-500 mb-3">Last 24 hours</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard label="Active users" value={metrics.active_users_24h} />
          <StatCard label="Uploads" value={metrics.uploads_24h} />
          <StatCard label="Queries" value={metrics.queries_24h} />
        </div>
      </div>

      {/* Tier distribution */}
      <div className="rounded-xl border p-4 bg-white dark:bg-zinc-900">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm text-zinc-500">Tier distribution</div>
          <div className="text-xs text-zinc-500">
            Free → Pro conversion:{" "}
            <span className="font-medium">{metrics.free_to_pro}%</span>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Bar label="Free" value={tiers.free} max={maxTier} />
          <Bar label="Mini+" value={tiers.mini} max={maxTier} />
          <Bar label="Pro" value={tiers.pro} max={maxTier} />
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-2 rounded border disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
        <span className="text-xs text-zinc-500">
          Uses <code>/admin/health</code>, <code>/admin/overview</code>,{" "}
          <code>/admin/metrics</code>
        </span>
      </div>
    </div>
  );
}
