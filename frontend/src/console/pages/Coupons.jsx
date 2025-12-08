// src/console/pages/Coupons.jsx
import { useEffect, useMemo, useState } from "react";
import { fetchJSON } from "../../lib/fetchJSON";
import Pagination from "../shared/Pagination";

const DEFAULT_LIMIT = 20;

function Field({ label, hint, children }) {
  return (
    <label className="text-sm">
      <div className="text-gray-600 mb-1">{label}</div>
      {children}
      {hint ? <div className="mt-1 text-xs text-gray-500">{hint}</div> : null}
    </label>
  );
}

function genCode(len = 8) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // avoid 0/1/O/I
  let out = "";
  for (let i = 0; i < len; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
}

export default function Coupons() {
  // list state
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // create form
  const [code, setCode] = useState("");
  const [discountType, setDiscountType] = useState("percent"); // "percent" | "fixed"
  const [currency, setCurrency] = useState("USD"); // only used for fixed
  const [value, setValue] = useState(10);
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [perUserLimit, setPerUserLimit] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState("");

  const fmt = (v) => (v == null || v === "" ? "—" : String(v));
  const fmtDate = (s) => (s ? new Date(s).toLocaleString() : "—");
  const fmtValue = (t, v, cur) => (t === "percent" ? `${v}%` : `${v} ${cur || ""}`.trim());

  const load = async (opts = {}) => {
    const nextOffset = opts.nextOffset ?? offset;
    const nextLimit = opts.nextLimit ?? limit;
    const search = opts.search ?? q;

    setLoading(true);
    setErr("");
    try {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      params.set("limit", String(nextLimit));
      params.set("offset", String(nextOffset));

      const data = await fetchJSON(`/api/v1/admin/coupons?${params.toString()}`);
      setRows(data?.items || []);
      setTotal(Number(data?.total || 0));
      setOffset(nextOffset);
      setLimit(nextLimit);
    } catch (e) {
      setErr(e.message || "Failed to load coupons");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load({ nextOffset: 0 });

  }, []);

  const onPageChange = (_page, newOffset) => load({ nextOffset: newOffset });
  const onSearch = () => load({ search: q, nextOffset: 0 });
  const onSearchKey = (e) => (e.key === "Enter" ? onSearch() : null);

  // ---- Validation helpers for create form ----
  const maxFixedForCurrency = currency === "USD" ? 10 : 100; // USD ≤ $10, INR ≤ ₹100
  const liveHint =
    discountType === "percent"
      ? "Allowed: 1–100 (%)"
      : `Allowed: 1–${maxFixedForCurrency} (${currency})`;

  const normalizeDate = (s) => {
    if (!s) return null;
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
  };

  const onCreate = async (e) => {
    e.preventDefault();
    setCreateErr("");

    const codeClean = code.trim().toUpperCase();
    if (!codeClean) return setCreateErr("Code is required");
    // quick client regex to mirror backend
    if (!/^[A-Z0-9_-]{3,32}$/.test(codeClean)) {
      return setCreateErr("Code must be 3–32 chars: A–Z, 0–9, _ or -");
    }

    const numVal = Number(value);
    if (!Number.isFinite(numVal) || numVal <= 0) {
      return setCreateErr("Value must be a positive number");
    }

    if (discountType === "percent") {
      if (numVal < 1 || numVal > 100) {
        return setCreateErr("Percent value must be between 1 and 100");
      }
    } else {
      if (numVal < 1 || numVal > maxFixedForCurrency) {
        return setCreateErr(`Fixed amount for ${currency} must be between 1 and ${maxFixedForCurrency}`);
      }
    }

    const toIntOrNull = (v) =>
      v === "" || v == null ? null : Math.max(1, parseInt(v, 10) || 0);

    const payload = {
      code: codeClean,
      discount_type: discountType,
      value: Math.round(numVal),
      max_redemptions: toIntOrNull(maxRedemptions),
      per_user_limit: toIntOrNull(perUserLimit),
      starts_at: normalizeDate(startsAt),
      ends_at: normalizeDate(endsAt),
      // Only meaningful for fixed; harmless if backend ignores for percent
      ...(discountType === "fixed" ? { currency } : {}),
    };

    setCreating(true);
    try {
      await fetchJSON(`/api/v1/admin/coupons`, {
        method: "POST",
        body: payload, // auto JSON-encoded by fetchJSON
      });

      // reset form
      setCode("");
      setDiscountType("percent");
      setCurrency("USD");
      setValue(10);
      setMaxRedemptions("");
      setPerUserLimit("");
      setStartsAt("");
      setEndsAt("");

      await load({ search: q, nextOffset: 0 });
    } catch (e) {
      setCreateErr(e.message || "Failed to create coupon");
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (id, codeHint) => {
    if (!window.confirm(`Delete coupon "${codeHint}"? This action cannot be undone.`)) return;
    try {
      await fetchJSON(`/api/v1/admin/coupons/${id}`, { method: "DELETE" });
      const newOffset = rows.length === 1 && offset > 0 ? Math.max(0, offset - limit) : offset;
      await load({ nextOffset: newOffset, search: q });
    } catch (e) {
      alert(e.message || "Failed to delete coupon");
    }
  };

  const countText = useMemo(
    () => (rows.length ? `${rows.length} row${rows.length > 1 ? "s" : ""}` : "—"),
    [rows.length]
  );

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Coupons</h2>

      {/* Create form */}
      <form onSubmit={onCreate} className="rounded-xl border p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Code" hint="A–Z, 0–9, _ or - (3–32 chars)">
          <div className="flex gap-2">
            <input
              className="border rounded px-3 py-2 w-full"
              placeholder="e.g., LAUNCH25"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              required
            />
            <button
              type="button"
              onClick={() => setCode((prev) => prev || genCode(8))}
              className="px-3 py-2 rounded border"
              title="Generate random code"
            >
              Generate
            </button>
          </div>
        </Field>

        <Field label="Type">
          <select
            className="border rounded px-3 py-2 w-full"
            value={discountType}
            onChange={(e) => setDiscountType(e.target.value)}
          >
            <option value="percent">Percent (%)</option>
            <option value="fixed">Fixed (in currency)</option>
          </select>
        </Field>

        {discountType === "fixed" && (
          <Field label="Currency">
            <select
              className="border rounded px-3 py-2 w-full"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              <option value="USD">USD (max 10)</option>
              <option value="INR">INR (max 100)</option>
            </select>
          </Field>
        )}

        <Field
          label={`Value (${discountType === "percent" ? "%" : `amount in ${currency}`})`}
          hint={liveHint}
        >
          <input
            type="number"
            min={1}
            max={discountType === "percent" ? 100 : (currency === "USD" ? 10 : 100)}
            className="border rounded px-3 py-2 w-full"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </Field>

        <Field label="Max redemptions (optional)">
          <input
            type="number"
            min={1}
            className="border rounded px-3 py-2 w-full"
            value={maxRedemptions}
            onChange={(e) => setMaxRedemptions(e.target.value)}
            placeholder="e.g., 100"
          />
        </Field>

        <Field label="Per-user limit (optional)">
          <input
            type="number"
            min={1}
            className="border rounded px-3 py-2 w-full"
            value={perUserLimit}
            onChange={(e) => setPerUserLimit(e.target.value)}
            placeholder="e.g., 1"
          />
        </Field>

        <Field label="Starts at (optional)">
          <input
            type="datetime-local"
            className="border rounded px-3 py-2 w-full"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
          />
        </Field>

        <Field label="Ends at (optional)">
          <input
            type="datetime-local"
            className="border rounded px-3 py-2 w-full"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
          />
        </Field>

        <div className="md:col-span-2 flex items-center gap-2">
          <button
            type="submit"
            disabled={creating}
            className="px-3 py-2 rounded bg-black text-white disabled:opacity-50"
          >
            {creating ? "Creating…" : "Create coupon"}
          </button>
          {createErr && <div className="text-sm text-red-600">{createErr}</div>}
        </div>
      </form>

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <input
            className="border rounded px-3 py-2 w-64"
            placeholder="Search by code/type"
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
            value={limit}
            onChange={(e) => load({ nextLimit: Number(e.target.value), nextOffset: 0 })}
            title="Rows per page"
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n} / page
              </option>
            ))}
          </select>
          <button
            onClick={() => load({ nextOffset: offset })}
            disabled={loading}
            className="px-3 py-2 rounded border disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {/* List */}
      {err && <div className="text-sm text-red-600">{err}</div>}

      <div className="overflow-auto border rounded">
        <table className="min-w-[1050px] w-full">
          <thead>
            <tr className="text-left text-sm text-gray-600">
              <th className="p-2">Code</th>
              <th className="p-2">Type</th>
              <th className="p-2">Value</th>
              <th className="p-2">Max</th>
              <th className="p-2">Per User</th>
              <th className="p-2">Starts</th>
              <th className="p-2">Ends</th>
              <th className="p-2">Created</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="p-2 font-mono">{c.code}</td>
                <td className="p-2">{c.discount_type}</td>
                <td className="p-2">{fmtValue(c.discount_type, c.value, c.currency)}</td>
                <td className="p-2">{fmt(c.max_redemptions)}</td>
                <td className="p-2">{fmt(c.per_user_limit)}</td>
                <td className="p-2">{fmtDate(c.starts_at)}</td>
                <td className="p-2">{fmtDate(c.ends_at)}</td>
                <td className="p-2">{fmtDate(c.created_at)}</td>
                <td className="p-2">
                  <button
                    onClick={() => onDelete(c.id, c.code)}
                    className="px-2 py-1 text-sm rounded border hover:bg-red-50"
                    title="Delete coupon"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!rows.length && !loading && (
              <tr>
                <td className="p-4 text-sm text-gray-500" colSpan={9}>
                  No coupons found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination total={total} limit={limit} offset={offset} onPageChange={onPageChange} />
      <div className="text-xs text-gray-500">{countText}</div>
    </div>
  );
}
