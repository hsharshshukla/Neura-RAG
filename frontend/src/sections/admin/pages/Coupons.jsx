// ============================
// File: src/sections/admin/Coupons.jsx
// ============================
import React, { useEffect, useState } from "react";
import secureAxios from "../../../utils/secureAxios";
import { isAdmin } from "../../../utils/auth";
import { useNavigate } from "react-router-dom";

const Input = (props) => (
  <input
    {...props}
    className={`mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${props.className || ""}`}
  />
);

const Label = ({ children }) => (
  <span className="block text-sm font-medium text-gray-700">{children}</span>
);

const Field = ({ label, children, required }) => (
  <label className="block mb-3">
    <Label>
      {label} {required && <span className="text-red-500">*</span>}
    </Label>
    {children}
  </label>
);

// Simple client-side code generator to prefill the Code field
function genCode(prefix = "SAVE", n = 6) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  let suffix = "";
  for (let i = 0; i < n; i++) suffix += alphabet[Math.floor(Math.random() * alphabet.length)];
  return `${prefix}${suffix}`;
}

export default function Coupons() {
  const nav = useNavigate();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [rows, setRows] = useState([]);
  const [deletingId, setDeletingId] = useState(null);

  const [form, setForm] = useState({
    code: "",
    name: "",
    amount: 0,
    amount_type: "percent",        // percent | fixed
    duration: "once",              // once | repeating | forever
    duration_in_months: "",
    starts_at: "",
    expires_at: "",
    is_limited_redemptions: false,
    max_redemptions: "",
    per_customer_limit: "",
    applies_to_variants: "",
    status: "active",
    currency: "",                  // only for fixed
  });

  useEffect(() => {
    if (!isAdmin()) { nav("/"); return; }
    (async () => {
      try {
        const { data } = await secureAxios.get("/admin/coupons");
        setRows(data || []);
      } catch {
        /* ignore */
      }
    })();
  }, [nav]);

  const needMonths = form.duration === "repeating";
  const isFixed = form.amount_type === "fixed";

  // Front-end caps: percent <= 100, fixed <= 10000 (₹100 in minor units)
  const maxAmount = isFixed ? 10000 : 100;

  const invalidReason =
    !isFixed && Number(form.amount) > 100
      ? "Percentage cannot exceed 100%."
      : isFixed && Number(form.amount) > 10000
      ? "Fixed amount cannot exceed ₹100 (i.e., 10000 minor units)."
      : null;

  const toInt = (v) => {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : undefined;
  };
  const toIntOrNull = (v) => {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : null;
  };

  function handleGenerateCode() {
    const prefix = form.amount_type === "percent" ? "PCT" : "OFF";
    setForm((f) => ({ ...f, code: genCode(prefix) }));
  }

  async function onSubmit(e) {
    e.preventDefault();
    setSaving(true); setError(""); setOk("");

    try {
      // Client-side guard (backend also enforces)
      const amt = toInt(form.amount) ?? 0;
      if (!isFixed && amt > 100) throw new Error("Percentage amount cannot exceed 100%");
      if (isFixed && amt > 10000) throw new Error("Fixed amount cannot exceed ₹100 (10000 minor units)");

      const payload = {
        code: (form.code || "").trim().toUpperCase(), // backend expects string, will be unique checked
        name: form.name.trim(),
        amount: amt,
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

      const { data } = await secureAxios.post("/admin/coupons", payload);
      setOk(`Created ${data.code}`);
      setRows(prev => [data, ...prev]);
      setForm(f => ({ ...f, code: "", name: "", amount: 0 }));
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || "Failed to create coupon";
      setError(String(msg));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(id) {
    if (!id) return;
    const row = rows.find(r => r.id === id);
    const name = row ? `${row.code} – ${row.name}` : `ID ${id}`;
    if (!window.confirm(`Delete coupon "${name}"? This cannot be undone.`)) return;

    setDeletingId(id);
    setError(""); setOk("");

    // Optimistic update
    const prev = rows;
    setRows(prev.filter(r => r.id !== id));
    try {
      await secureAxios.delete(`/admin/coupons/${id}`);
      setOk("Coupon deleted.");
    } catch (err) {
      // revert UI
      setRows(prev);
      const msg = err?.response?.data?.detail || err.message || "Failed to delete coupon";
      setError(String(msg));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-6">Coupons</h1>

      <form onSubmit={onSubmit} className="bg-white shadow rounded-xl p-6 mb-8">
        {error && <div className="p-3 rounded bg-red-50 text-red-800 text-sm mb-3">{error}</div>}
        {ok && <div className="p-3 rounded bg-green-50 text-green-800 text-sm mb-3">{ok}</div>}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Code">
            <div className="flex gap-2">
              <Input
                value={form.code}
                onChange={e => setForm({ ...form, code: e.target.value })}
                placeholder="(required) e.g., PCTAB12"
              />
              <button
                type="button"
                onClick={handleGenerateCode}
                className="whitespace-nowrap rounded-md border px-3 py-2 text-sm hover:bg-gray-50"
              >
                Generate
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Use Generate to prefill; must still be unique.
            </p>
          </Field>

          <Field label="Name" required>
            <Input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="25% off for beta users" />
          </Field>

          <Field label={`Amount (${isFixed ? "minor units" : "%"})`} required>
            <Input
              type="number"
              min="0"
              max={maxAmount}
              required
              value={form.amount}
              onChange={e => {
                const raw = Number(e.target.value) || 0;
                const clamped = Math.max(0, Math.min(maxAmount, raw));
                setForm({ ...form, amount: clamped });
              }}
            />
            {!isFixed ? (
              <p className="text-xs text-gray-500 mt-1">Percent 0–100. (Hard limit: 100%)</p>
            ) : (
              <p className="text-xs text-gray-500 mt-1">Fixed uses minor units (₹1.00 = 100). Max ₹100 ⇒ 10000.</p>
            )}
            {invalidReason && <div className="mt-1 text-xs text-red-600">{invalidReason}</div>}
          </Field>

          <Field label="Amount Type" required>
            <select className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm" value={form.amount_type}
              onChange={e => setForm({ ...form, amount_type: e.target.value })}>
              <option value="percent">percent</option>
              <option value="fixed">fixed</option>
            </select>
          </Field>

          <Field label="Duration" required>
            <select className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm" value={form.duration}
              onChange={e => setForm({ ...form, duration: e.target.value })}>
              <option value="once">once</option>
              <option value="repeating">repeating</option>
              <option value="forever">forever</option>
            </select>
          </Field>

          {needMonths && (
            <Field label="Duration in months" required>
              <Input type="number" min="1" value={form.duration_in_months}
                onChange={e => setForm({ ...form, duration_in_months: e.target.value })} />
            </Field>
          )}

          <Field label="Starts At (UTC)">
            <Input type="datetime-local" value={form.starts_at}
              onChange={e => setForm({ ...form, starts_at: e.target.value })} />
          </Field>

          <Field label="Expires At (UTC)">
            <Input type="datetime-local" value={form.expires_at}
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
              <Input type="number" min="1" value={form.max_redemptions}
                onChange={e => setForm({ ...form, max_redemptions: e.target.value })} />
            </Field>
          )}

          <Field label="Per-customer limit">
            <Input type="number" min="0" value={form.per_customer_limit}
              onChange={e => setForm({ ...form, per_customer_limit: e.target.value })} />
            <p className="text-xs text-gray-500 mt-1">Blank = unlimited; set 1 for first-purchase only.</p>
          </Field>

          <Field label="Applies to variant IDs (comma-separated)">
            <Input placeholder="e.g., 1,2,3" value={form.applies_to_variants}
              onChange={e => setForm({ ...form, applies_to_variants: e.target.value })} />
          </Field>

          {isFixed && (
            <Field label="Currency (for fixed)">
              <Input placeholder="INR" value={form.currency}
                onChange={e => setForm({ ...form, currency: e.target.value })} />
            </Field>
          )}

          <Field label="Status" required>
            <select className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm" value={form.status}
              onChange={e => setForm({ ...form, status: e.target.value })}>
              <option value="active">active</option>
              <option value="inactive">inactive</option>
              <option value="draft">draft</option>
            </select>
          </Field>
        </div>

        <button
          type="submit"
          className="mt-4 px-4 py-2 rounded-md bg-indigo-600 text-white disabled:opacity-50"
          disabled={saving || !!invalidReason}
        >
          {saving ? "Creating…" : "Create Coupon"}
        </button>
      </form>

      <div className="bg-white shadow rounded-xl p-6">
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
                <th className="py-2 pr-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t">
                  <td className="py-2 pr-3 font-mono">{c.code}</td>
                  <td className="py-2 pr-3">{c.name}</td>
                  <td className="py-2 pr-3">{c.amount_type}</td>
                  <td className="py-2 pr-3">{c.amount_type === "percent" ? `${c.amount}%` : c.amount}</td>
                  <td className="py-2 pr-3">
                    {c.duration}{c.duration === "repeating" ? ` (${c.duration_in_months})` : ""}
                  </td>
                  <td className="py-2 pr-3">{c.status}</td>
                  <td className="py-2 pr-3">{c.starts_at ? new Date(c.starts_at).toLocaleString() : "-"}</td>
                  <td className="py-2 pr-3">{c.expires_at ? new Date(c.expires_at).toLocaleString() : "-"}</td>
                  <td className="py-2 pr-3">
                    <button
                      className="text-red-600 hover:text-red-700 disabled:opacity-50"
                      onClick={() => onDelete(c.id)}
                      disabled={deletingId === c.id}
                      title="Delete coupon"
                    >
                      {deletingId === c.id ? "Deleting…" : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan="9" className="py-6 text-gray-500">No coupons yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
