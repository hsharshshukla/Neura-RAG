import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from "recharts";
import secureAxios from "../../utils/secureAxios";

// ------------------------------
// Helpers
// ------------------------------
const fmtInt = (n) => (n == null ? "-" : Number(n).toLocaleString());
const fmtMs = (n) => (n == null ? "-" : `${n} ms`);
const fmtRate = (n) => (n == null ? "-" : `${(n * 100).toFixed(0)}%`);
const fmtUsd = (n) => {
  if (n == null) return "-";
  const v = typeof n === "string" ? parseFloat(n) : n;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 4,
  }).format(v || 0);
};

// ------------------------------
// Data hooks (axios-based)
// ------------------------------
function useSummary(range) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/summary`, { params: { range } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range]);
  return { data };
}

function usePerf(range, groupBy) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/perf`, { params: { group_by: groupBy, range } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range, groupBy]);
  return { data };
}

function useRagInsights(range) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/insights/rag`, { params: { range } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range]);
  return { data };
}

function useQualityInsights(range) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/insights/quality`, { params: { range } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range]);
  return { data };
}

// --- NEW: actives, usage, and user lists ---
function useActives(range, granularity) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/actives`, { params: { range, granularity } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range, granularity]);
  return { data };
}

function useUsageVsLimits(range) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/usage_vs_limits`, { params: { range } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range]);
  return { data };
}

function useTopUploads(range, limit = 50) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    secureAxios
      .get(`/admin/analytics/users/uploads`, { params: { range, limit } })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range, limit]);
  return { data };
}

function useTopTokenUsers(range, plan, limit = 50) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    const params = { range, limit };
    if (plan && plan !== "all") params.plan = plan;
    secureAxios
      .get(`/admin/analytics/users/token_usage`, { params })
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [range, plan, limit]);
  return { data };
}

// ------------------------------
// UI Bits
// ------------------------------
const Card = ({ title, value, sub }) => (
  <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
    <div className="text-xs uppercase tracking-wide text-zinc-500">{title}</div>
    <div className="mt-2 text-2xl font-semibold text-zinc-900">{value}</div>
    {sub ? <div className="mt-1 text-xs text-zinc-500">{sub}</div> : null}
  </div>
);

const SectionTitle = ({ children, right }) => (
  <div className="mb-3 flex items-center justify-between">
    <h2 className="text-lg font-semibold text-zinc-900">{children}</h2>
    {right}
  </div>
);

const RangePicker = ({ range, setRange }) => {
  const ranges = ["24h", "7d", "30d", "90d"];
  return (
    <div className="inline-flex rounded-xl border border-zinc-200 bg-white p-1">
      {ranges.map((r) => (
        <button
          key={r}
          className={`px-3 py-1 text-sm rounded-lg ${
            range === r ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100"
          }`}
          onClick={() => setRange(r)}
        >
          {r}
        </button>
      ))}
    </div>
  );
};

const GranularityPicker = ({ value, onChange }) => {
  const opts = ["day", "week", "month"];
  return (
    <div className="inline-flex rounded-xl border border-zinc-200 bg-white p-1">
      {opts.map((g) => (
        <button
          key={g}
          className={`px-3 py-1 text-sm rounded-lg ${
            value === g ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100"
          }`}
          onClick={() => onChange(g)}
        >
          {g}
        </button>
      ))}
    </div>
  );
};

const PlanFilter = ({ value, onChange }) => {
  const opts = ["all", "free", "base", "mini", "pro"];
  return (
    <div className="inline-flex rounded-xl border border-zinc-200 bg-white p-1">
      {opts.map((p) => (
        <button
          key={p}
          className={`px-3 py-1 text-sm rounded-lg ${
            value === p ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100"
          }`}
          onClick={() => onChange(p)}
        >
          {p}
        </button>
      ))}
    </div>
  );
};

const RefreshButton = ({ days = 7, onDone }) => {
  const [loading, setLoading] = useState(false);
  return (
    <button
      className={`rounded-xl border px-3 py-2 text-sm ${loading ? "opacity-60" : "hover:bg-zinc-50"}`}
      onClick={() => {
        setLoading(true);
        secureAxios
          .post(`/admin/analytics/refresh`, {
            days,
            refresh_sessions: true,
            refresh_daily: true,
          })
          .then(() => onDone && onDone())
          .finally(() => setLoading(false));
      }}
      disabled={loading}
      title="Recompute recent rollups"
    >
      {loading ? "Refreshing…" : `Refresh last ${days}d`}
    </button>
  );
};

// ------------------------------
// Main Page
// ------------------------------
export default function ChatAnalytics() {
  const [range, setRange] = useState("7d");
  const [granularity, setGranularity] = useState("day");
  const [tierFilter, setTierFilter] = useState("all");

  const { data: summary } = useSummary(range);
  const { data: perfByModel } = usePerf(range, "model");
  const { data: perfByDay } = usePerf(range, "day");
  const { data: rag } = useRagInsights(range);
  const { data: quality } = useQualityInsights(range);

  const { data: actives } = useActives(range, granularity);
  const { data: usage } = useUsageVsLimits(range);
  const { data: uploads } = useTopUploads(range, 50);
  const { data: tokenUsers } = useTopTokenUsers(range, tierFilter, 50);

  const perfByDaySeries = useMemo(() => {
    const rows = (perfByDay && perfByDay.rows) || [];
    return rows.map((r) => ({
      day: r.group_key,
      p50: r.latency_p50_ms ?? 0,
      p90: r.latency_p90_ms ?? 0,
      messages: r.messages,
      errors: Math.round((r.error_rate || 0) * 100),
    }));
  }, [perfByDay]);

  const activesSeries = useMemo(() => {
    const rows = (actives && actives.rows) || [];
    return rows.map((r) => ({
      bucket: r.bucket,
      active_chats: r.active_chats,
      messages: r.messages,
    }));
  }, [actives]);

  const usageRows = (usage && usage.rows) || [];
  const uploadRows = (uploads && uploads.rows) || [];
  const tokenUserRows = (tokenUsers && tokenUsers.rows) || [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Chat Analytics</h1>
        <div className="flex items-center gap-2">
          <RangePicker range={range} setRange={setRange} />
          <RefreshButton days={range === "24h" ? 2 : 7} />
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        <Card title="Messages" value={fmtInt(summary?.messages)} />
        <Card title="Sessions" value={fmtInt(summary?.sessions)} />
        <Card title="p50 Latency" value={fmtMs(summary?.latency_p50_ms)} />
        <Card title="p90 Latency" value={fmtMs(summary?.latency_p90_ms)} />
        <Card title="RAG Hit" value={fmtRate(summary?.rag_hit_rate)} />
        <Card title="Thumbs Up" value={fmtRate(summary?.thumbs_up_rate)} />
        <Card title="CSAT" value={summary?.csat_avg ?? "-"} />
        <Card title="Cost" value={fmtUsd(summary?.total_cost)} />
      </div>

      {/* Perf by model */}
      <div className="mt-8">
        <SectionTitle>Performance by Model</SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={(perfByModel && perfByModel.rows) || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="group_key" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} />
              <Tooltip formatter={(val, name) => [val, name]} />
              <Legend />
              <Bar yAxisId="left" dataKey="messages" name="Messages" fill="#8884d8" />
              <Bar yAxisId="left" dataKey="input_tokens" name="Input Tokens" fill="#82ca9d" />
              <Bar yAxisId="left" dataKey="output_tokens" name="Output Tokens" fill="#ffc658" />
              <Bar yAxisId="right" dataKey="latency_p50_ms" name="p50 (ms)" fill="#a0aec0" />
              <Bar yAxisId="right" dataKey="latency_p90_ms" name="p90 (ms)" fill="#718096" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Perf by day */}
      <div className="mt-8">
        <SectionTitle>Latency Trend (Daily)</SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={perfByDaySeries}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="day" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="p50" name="p50 (ms)" stroke="#8884d8" dot={false} />
              <Line type="monotone" dataKey="p90" name="p90 (ms)" stroke="#82ca9d" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Active chats */}
      <div className="mt-8">
        <SectionTitle right={<GranularityPicker value={granularity} onChange={setGranularity} />}>
          Active Chats ({granularity})
        </SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={activesSeries}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="bucket" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="active_chats" name="Active Chats" fill="#8884d8" />
              <Bar dataKey="messages" name="Messages" fill="#82ca9d" />
            </BarChart>
          </ResponsiveContainer>
          {!activesSeries?.length && (
            <div className="mt-3 text-sm text-zinc-500">No data in the selected window.</div>
          )}
        </div>
      </div>

      {/* Tokens by plan (vs monthly limits) */}
      <div className="mt-8">
        <SectionTitle>Tokens by Plan (vs. monthly limits)</SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500">
                <th className="py-2">Plan</th>
                <th className="py-2">Input</th>
                <th className="py-2">Output</th>
                <th className="py-2">Total</th>
                <th className="py-2">Monthly Limit</th>
                <th className="py-2">Usage %</th>
                <th className="py-2">Remaining</th>
              </tr>
            </thead>
            <tbody>
              {usageRows.map((r) => {
                const pct = r.pct_of_limit == null ? null : Math.min(Math.max(r.pct_of_limit, 0), 1);
                return (
                  <tr key={r.plan} className="border-t">
                    <td className="py-2">{r.plan}</td>
                    <td className="py-2">{fmtInt(r.input_tokens)}</td>
                    <td className="py-2">{fmtInt(r.output_tokens)}</td>
                    <td className="py-2">{fmtInt(r.total_tokens)}</td>
                    <td className="py-2">{r.monthly_limit == null ? "Unlimited" : fmtInt(r.monthly_limit)}</td>
                    <td className="py-2">{pct == null ? "-" : `${(pct * 100).toFixed(0)}%`}</td>
                    <td className="py-2">{r.remaining == null ? "-" : fmtInt(r.remaining)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!usageRows?.length && (
            <div className="mt-3 text-sm text-zinc-500">No token data in the selected window.</div>
          )}
        </div>
      </div>

      {/* Top users by uploads */}
      <div className="mt-8">
        <SectionTitle>Top Users by Uploads</SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500">
                <th className="py-2">User</th>
                <th className="py-2">Files</th>
                <th className="py-2">Size (bytes)</th>
              </tr>
            </thead>
            <tbody>
              {(uploads?.rows || []).map((r, i) => (
                <tr key={`${r.user_email || r.user_id}-${i}`} className="border-t">
                  <td className="py-2">{r.user_email || r.user_id}</td>
                  <td className="py-2">{fmtInt(r.files)}</td>
                  <td className="py-2">{fmtInt(r.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!((uploads?.rows || []).length) && (
            <div className="mt-3 text-sm text-zinc-500">
              No uploads found for the selected window (or uploads table not detected).
            </div>
          )}
        </div>
      </div>

      {/* Top users by token usage (with tier filter) */}
      <div className="mt-8">
        <SectionTitle right={<PlanFilter value={tierFilter} onChange={setTierFilter} />}>
          Top Users by Token Usage {tierFilter !== "all" ? `(${tierFilter})` : ""}
        </SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500">
                <th className="py-2">User</th>
                <th className="py-2">Plan</th>
                <th className="py-2">Input</th>
                <th className="py-2">Output</th>
                <th className="py-2">Total</th>
              </tr>
            </thead>
            <tbody>
              {(tokenUsers?.rows || []).map((r, i) => (
                <tr key={`${r.user_email || r.user_id}-${i}`} className="border-t">
                  <td className="py-2">{r.user_email || r.user_id}</td>
                  <td className="py-2">{r.plan}</td>
                  <td className="py-2">{fmtInt(r.input_tokens)}</td>
                  <td className="py-2">{fmtInt(r.output_tokens)}</td>
                  <td className="py-2">{fmtInt(r.total_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!((tokenUsers?.rows || []).length) && (
            <div className="mt-3 text-sm text-zinc-500">No usage found in the selected window.</div>
          )}
        </div>
      </div>

      {/* RAG insights */}
      <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <SectionTitle>Top Docs (by hits)</SectionTitle>
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-zinc-500">
                  <th className="py-2">Doc Hash</th>
                  <th className="py-2">Retrieved</th>
                  <th className="py-2">Hits</th>
                  <th className="py-2">Hit Rate</th>
                </tr>
              </thead>
              <tbody>
                {(rag?.top_docs || []).map((r) => (
                  <tr key={r.doc_hash} className="border-t">
                    <td className="py-2 font-mono text-xs">{r.doc_hash}</td>
                    <td className="py-2">{fmtInt(r.retrieved)}</td>
                    <td className="py-2">{fmtInt(r.hits)}</td>
                    <td className="py-2">{fmtRate(r.hit_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!((rag?.top_docs || []).length) && (
              <div className="mt-3 text-sm text-zinc-500">No RAG hits yet.</div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <SectionTitle>Source Mix</SectionTitle>
          <ul className="space-y-1 text-sm">
            {(rag?.source_mix || []).map((s) => (
              <li key={s.kind} className="flex items-center justify-between">
                <span className="text-zinc-700">{s.kind}</span>
                <span className="font-medium">{fmtInt(s.cnt)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-6">
            <SectionTitle>Zero-Hit Docs</SectionTitle>
            <div className="max-h-40 overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-zinc-500">
                    <th className="py-2">Doc Hash</th>
                    <th className="py-2">Retrieved</th>
                  </tr>
                </thead>
                <tbody>
                  {(rag?.zero_hit_docs || []).map((r) => (
                    <tr key={r.doc_hash} className="border-t">
                      <td className="py-2 font-mono text-xs">{r.doc_hash}</td>
                      <td className="py-2">{fmtInt(r.retrieved)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!((rag?.zero_hit_docs || []).length) && (
                <div className="mt-3 text-sm text-zinc-500">Nothing retrieved without hits.</div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Quality */}
      <div className="mt-8">
        <SectionTitle>Quality</SectionTitle>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card title="Thumbs Up" value={fmtRate(quality?.thumbs_up_rate)} />
            <Card title="CSAT" value={quality?.csat_avg ?? "-"} />
          </div>
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-medium text-zinc-700">Recent Feedback</h3>
            <div className="max-h-64 overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-zinc-500">
                    <th className="py-2">When</th>
                    <th className="py-2">Model</th>
                    <th className="py-2">Thumb</th>
                    <th className="py-2">CSAT</th>
                    <th className="py-2">Comment</th>
                  </tr>
                </thead>
                <tbody>
                  {(quality?.recent_feedback || []).map((f) => (
                    <tr key={f.event_id} className="border-t align-top">
                      <td className="py-2 text-xs text-zinc-600">{new Date(f.ts).toLocaleString()}</td>
                      <td className="py-2 text-xs">{f.model}</td>
                      <td className="py-2 text-xs">{f.thumb}</td>
                      <td className="py-2 text-xs">{f.csat}</td>
                      <td className="py-2 text-xs">{f.feedback_comment}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!((quality?.recent_feedback || []).length) && (
                <div className="mt-3 text-sm text-zinc-500">No feedback captured yet.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
