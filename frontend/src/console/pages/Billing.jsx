// src/console/pages/Billing.jsx
import { useEffect, useState } from "react";
import { fetchJSON } from "../../lib/fetchJSON";
import StatCard from "../shared/StatCard";

export default function Billing() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const d = await fetchJSON("/api/v1/admin/billing/stats");
      setStats(d || {});
    } catch (e) {
      setErr(e.message || "Failed to load billing stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Billing</h2>
        <button onClick={load} className="px-3 py-2 rounded border" disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}
      {!stats ? null : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard label="Active Pro" value={stats["Active Pro"] ?? 0} />
            <StatCard label="Active Mini" value={stats["Active Mini"] ?? 0} />
            <StatCard label="Active Free" value={stats["Active Free"] ?? 0} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard label="MRR" value={stats["MRR"] ?? "—"} hint="From Lemon Squeezy later" />
            <StatCard label="Failed Payments" value={stats["Failed Payments"] ?? 0} />
            <StatCard label="Total Users" value={stats["Total Users"] ?? 0} />
          </div>
        </>
      )}
    </div>
  );
}
