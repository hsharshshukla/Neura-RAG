// frontend/src/pages/AdminCoupons.jsx
import React, { useEffect, useMemo, useState } from "react";
import secureAxios from "../utils/secureAxios";
import { isAdmin } from "../utils/auth";
import { useNavigate } from "react-router-dom";

const Field = ({ label, children, required }) => (
  <label className="block mb-3">
    <span className="block text-sm font-medium text-gray-700">
      {label} {required && <span className="text-red-500">*</span>}
    </span>
    {children}
  </label>
);

export default function AdminCoupons() {
  const nav = useNavigate();
  const [form, setForm] = useState({
    code: "",
    name: "",
    amount: 0,
    amount_type: "percent",
    duration: "once",
    duration_in_months: "",
    starts_at: "",
    expires_at: "",
    is_limited_redemptions: false,
    max_redemptions: "",
    per_customer_limit: "",
    applies_to_variants: "",
    status: "active",
    currency: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [coupons, setCoupons] = useState([]);

  useEffect(() => {
    if (!isAdmin()) {
      nav("/"); // or show 403
      return;
    }
    (async () => {
      try {
        const { data } = await secureAxios.get("/api/v1/admin/coupons");
        setCoupons(data || []);
      } catch (e) { /* ignore listing errors */ }
    })();
  }, [nav]);

  const needMonths = form.duration === "repeating";
  const isFixed = form.amount_type === "fixed";

  function toInt(v) {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : undefined;
  }
  function toIntOrNull(v) {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : null;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setOk("");

    try {
      const payload = {
        code: form.code.trim().toUpperCase(),
        name: form.name.trim(),
        amount: toInt(form.amount) ?? 0,
        amount_type: form.amount_type,
        duration: form.duration,
        duration_in_months: needMonths ? toInt(form.duration_in_months) : null,
        starts_at: form.starts_at ? new Date(form.starts_at).toISOString() : null,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
        is_limited_redemptions: !!form.is_limited_redemptions,
        max_redemptions: form.is_limited_redemptions ? toIntOrNull(form.max_redemptions) : null,
        per_customer_limit: form.per_customer_limit ? toIntOrNull(form.per_customer_limit) : null,
        applies_to_variants: form.applies_to_variants
          ? form.applies_to_variants.split(",").map(s => parseInt(s.trim(), 10)).filter(Number.isFinite)
          : null,
        status: form.status,
        currency: isFixed && form.currency ? form.currency.toUpperCase() : null,
      };

      const { data } = await secureAxios.post("/api/v1/admin/coupons", payload);
      setOk(`Created coupon ${data.code}`);
      setCoupons(prev => [data, ...prev]);
      // reset minimal
      setForm(f => ({ ...f, code: "", name: "", amount: 0 }));
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || "Failed to create coupon";
      setError(String(msg));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-semibold mb-6">Admin • Create Coupon</h1>

      <form onSubmit={handleSubmit} className="bg-white shadow rounded-xl p-6 space-y-4">
        {error && <div className="p-3 rounded bg-red-50 text-red-800 text-sm">{error}</div>}
        {ok && <div className="p-3 rounded bg-green-50 text-green-800 text-sm">{ok}</div>}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Code" required>
            <input className="input" required value={form.code}
              onChange={e => setForm({ ...form, code: e.target.value })}
              placeholder="BETA25" />
          </Field>

          <Field label="Name" required>
            <input className="input" required value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="25% off for beta users" />
          </Field>

          <Field label="Amount" required>
            <input className="input" type="number" min="0" required value={form.amount}
              onChange={e => setForm({ ...form, amount: e.target.value })} />
            <p className="text-xs text-gray-500 mt-1">
              If percent: 0–100. If fixed: enter minor units (e.g., 100 = ₹1.00).
            </p>
          </Field>

          <Field label="Amount Type" required>
            <select className="input" value={form.amount_type}
              onChange={e => setForm({ ...form, amount_type: e.target.value })}>
              <option value="percent">percent</option>
              <option value="fixed">fixed</option>
            </select>
          </Field>

          <Field label="Duration" required>
            <select className="input" value={form.duration}
              onChange={e => setForm({ ...form, duration: e.target.value })}>
              <option value="once">once</option>
              <option value="repeating">repeating</option>
              <option value="forever">forever</option>
            </select>
          </Field>

          {needMonths && (
            <Field label="Duration in months" required>
              <input className="input" type="number" min="1" value={form.duration_in_months}
                onChange={e => setForm({ ...form, duration_in_months: e.target.value })} />
            </Field>
          )}

          <Field label="Starts At (UTC)">
            <input className="input" type="datetime-local" value={form.starts_at}
              onChange={e => setForm({ ...form, starts_at: e.target.value })} />
          </Field>

          <Field label="Expires At (UTC)">
            <input className="input" type="datetime-local" value={form.expires_at}
              onChange={e => setForm({ ...form, expires_at: e.target.value })} />
          </Field>

          <Field label="Limit total redemptions?">
            <div className="flex items-center gap-2">
              <input id="limit" type="checkbox" checked={form.is_limited_redemptions}
                onChange={e => setForm({ ...form, is_limited_redemptions: e.target.checked })} />
              <label htmlFor="limit">Enable</label>
            </div>
          </Field>

          {form.is_limited_redemptions && (
            <Field label="Max redemptions">
              <input className="input" type="number" min="1" value={form.max_redemptions}
                onChange={e => setForm({ ...form, max_redemptions: e.target.value })} />
            </Field>
          )}

          <Field label="Per-customer limit">
            <input className="input" type="number" min="0" value={form.per_customer_limit}
              onChange={e => setForm({ ...form, per_customer_limit: e.target.value })} />
            <p className="text-xs text-gray-500 mt-1">Leave blank for unlimited per user; set 1 for first-purchase only.</p>
          </Field>

          <Field label="Applies to variant IDs (comma-separated)">
            <input className="input" placeholder="e.g., 1,2,3"
              value={form.applies_to_variants}
              onChange={e => setForm({ ...form, applies_to_variants: e.target.value })} />
          </Field>

          <Field label="Status" required>
            <select className="input" value={form.status}
              onChange={e => setForm({ ...form, status: e.target.value })}>
              <option value="active">active</option>
              <option value="inactive">inactive</option>
              <option value="draft">draft</option>
            </select>
          </Field>

          {isFixed && (
            <Field label="Currency (for fixed)">
              <input className="input" placeholder="INR" value={form.currency}
                onChange={e => setForm({ ...form, currency: e.target.value })} />
            </Field>
          )}
        </div>

        <button
          type="submit"
          className="px-4 py-2 rounded-md bg-indigo-600 text-white disabled:opacity-50"
          disabled={saving}
        >
          {saving ? "Creating…" : "Create Coupon"}
        </button>
      </form>

      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-3">Recent Coupons</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-600">
                <th className="py-2 pr-3">Code</th>
                <th className="py-2 pr-3">Name</th>
                <th className="py-2 pr-3">Type</th>
                <th className="py-2 pr-3">Amount</th>
                <th className="py-2 pr-3">Duration</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Starts</th>
                <th className="py-2 pr-3">Expires</th>
              </tr>
            </thead>
            <tbody>
              {coupons.map(c => (
                <tr key={c.id} className="border-t">
                  <td className="py-2 pr-3 font-mono">{c.code}</td>
                  <td className="py-2 pr-3">{c.name}</td>
                  <td className="py-2 pr-3">{c.amount_type}</td>
                  <td className="py-2 pr-3">
                    {c.amount_type === "percent" ? `${c.amount}%` : c.amount}
                  </td>
                  <td className="py-2 pr-3">
                    {c.duration}{c.duration === "repeating" && ` (${c.duration_in_months})`}
                  </td>
                  <td className="py-2 pr-3">{c.status}</td>
                  <td className="py-2 pr-3">{c.starts_at ? new Date(c.starts_at).toLocaleString() : "-"}</td>
                  <td className="py-2 pr-3">{c.expires_at ? new Date(c.expires_at).toLocaleString() : "-"}</td>
                </tr>
              ))}
              {!coupons.length && (
                <tr><td colSpan="8" className="py-6 text-gray-500">No coupons yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
