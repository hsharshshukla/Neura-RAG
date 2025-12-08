// src/console/pages/Users.jsx
import { useEffect, useMemo, useState, useCallback } from "react";
import { fetchJSON } from "../../lib/fetchJSON";
import Pagination from "../shared/Pagination";

const DEFAULT_LIMIT = 20;

// --- UI bits ---------------------------------------------------------------

function Pill({ children, tone = "zinc" }) {
  const tones = {
    zinc: "bg-zinc-100 text-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-100",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-100",
    indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-100",
    gray: "bg-gray-100 text-gray-800 dark:bg-gray-900/40 dark:text-gray-100",
    red: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-100",
  };
  return (
    <span className={`px-2 py-0.5 text-xs rounded-full ${tones[tone] || tones.zinc}`}>
      {children}
    </span>
  );
}

function Modal({ open, onClose, onSave, user }) {
  const [saving, setSaving] = useState(false);
  const [tier, setTier] = useState(user?.tier || "free");
  const [role, setRole] = useState((user?.role || "user").toLowerCase());

  useEffect(() => {
    if (open) {
      setTier((user?.tier || "free").toLowerCase());
      setRole((user?.role || "user").toLowerCase());
    }
  }, [open, user]);

  if (!open) return null;

  const doSave = async () => {
    if (!user?.email) return;
    setSaving(true);
    try {
      await onSave({ email: user.email, tier, role });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-2xl border bg-white dark:bg-zinc-900 dark:border-zinc-700 shadow-xl">
        <div className="p-4 border-b dark:border-zinc-700">
          <div className="text-sm text-zinc-500">Edit user</div>
          <div className="font-medium truncate">{user?.email}</div>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <div className="text-sm text-zinc-500 mb-1">Tier</div>
            <select
              className="w-full border rounded px-3 py-2 text-sm"
              value={tier}
              onChange={(e) => setTier(e.target.value)}
            >
              <option value="free">free</option>
              <option value="mini">mini</option>
              <option value="pro">pro</option>
            </select>
          </div>

          <div>
            <div className="text-sm text-zinc-500 mb-1">Role</div>
            {/* Map to existing backend (user/admin only) */}
            <select
              className="w-full border rounded px-3 py-2 text-sm"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
            <div className="mt-1 text-xs text-zinc-500">
              (Role changes use <code>promote</code>/<code>demote</code> endpoints.)
            </div>
          </div>
        </div>
        <div className="p-4 flex items-center justify-end gap-2 border-t dark:border-zinc-700">
          <button onClick={onClose} disabled={saving} className="px-3 py-2 text-sm rounded border">
            Cancel
          </button>
          <button
            onClick={doSave}
            disabled={saving}
            className="px-3 py-2 text-sm rounded bg-black text-white disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// --- Page -------------------------------------------------------------------

export default function Users() {
  // list state
  const [rows, setRows] = useState([]);             // current page rows
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // edit modal state
  const [editOpen, setEditOpen] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [busyEmail, setBusyEmail] = useState("");

  // bulk selection state
  const [selected, setSelected] = useState(() => new Set()); // holds user IDs (as strings for Set ergonomics)
  const selectedCount = selected.size;

  // bulk action extra inputs
  const [bulkReason, setBulkReason] = useState("");
  const [bulkRole, setBulkRole] = useState("User");
  const allowedRoles = ["Owner", "Admin", "Support", "Finance", "Analyst", "ReadOnly", "User"];

  const fmtDate = (s) => (s ? new Date(s).toLocaleString() : "—");
  const roleTone = (r) => (r?.toLowerCase() === "admin" ? "indigo" : r?.toLowerCase() === "owner" ? "red" : "zinc");
  const tierTone = (t) => (t === "pro" ? "green" : t?.startsWith("mini") ? "indigo" : "gray");
  const statusTone = (s) => (s === "active" ? "green" : s === "deactivated" ? "red" : "zinc");

  // --- data load ------------------------------------------------------------
  const load = useCallback(
    async (opts = {}) => {
      const nextOffset = opts.nextOffset ?? offset;
      const nextLimit = opts.nextLimit ?? limit;
      const search = opts.search ?? q;
      const tier = opts.tier ?? tierFilter;

      setLoading(true);
      setErr("");
      try {
        const params = new URLSearchParams();
        if (search) params.set("q", search);
        if (tier) params.set("tier", tier);
        params.set("limit", String(nextLimit));
        params.set("offset", String(nextOffset));

        const data = await fetchJSON(`/api/v1/admin/users?${params.toString()}`);
        setRows(data?.items || []);
        setTotal(Number(data?.total || 0));
        setOffset(nextOffset);
        setLimit(nextLimit);
      } catch (e) {
        setErr(e.message || "Failed to load users");
        setRows([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [offset, limit, q, tierFilter]
  );

  useEffect(() => {
    load({ nextOffset: 0 });
  }, [load]);

  // --- table helpers --------------------------------------------------------
  const onPageChange = (_page, newOffset) => {
    setSelected(new Set()); // clear selection when changing page
    load({ nextOffset: newOffset });
  };

  const onSearch = () => {
    setSelected(new Set());
    load({ search: q, tier: tierFilter, nextOffset: 0 });
  };
  const onSearchKey = (e) => (e.key === "Enter" ? onSearch() : null);
  const onTierFilterChange = (val) => {
    setTierFilter(val);
    setSelected(new Set());
    load({ tier: val, search: q, nextOffset: 0 });
  };

  const clearFilters = () => {
    setQ("");
    setTierFilter("");
    setSelected(new Set());
    load({ search: "", tier: "", nextOffset: 0 });
  };

  // --- single-user actions --------------------------------------------------
  const logoutAll = async (email) => {
    if (!window.confirm(`Force logout all sessions for ${email}?`)) return;
    setBusyEmail(email);
    try {
      await fetchJSON(`/api/v1/admin/users/logout-all`, {
        method: "POST",
        body: { email }, // fetchJSON will JSON-encode + set headers
      });
      await load({ nextOffset: offset, search: q, tier: tierFilter });
    } catch (e) {
      alert(e.message || "Failed to logout user");
    } finally {
      setBusyEmail("");
    }
  };

  // Save changes from modal (tier + legacy role mapping)
  const applyChanges = async ({ email, tier, role }) => {
    setBusyEmail(email);
    const original = rows.find((r) => r.email === email);
    const origTier = (original?.tier || "free").toLowerCase();
    const origRole = (original?.role || "user").toLowerCase();

    try {
      // 1) Tier change
      if (tier !== origTier) {
        await fetchJSON(`/api/v1/admin/users/set-tier`, {
          method: "POST",
          body: { email, tier },
        });
      }
      // 2) Role change via promote/demote (legacy)
      if (role !== origRole) {
        if (role === "admin" && origRole !== "admin") {
          await fetchJSON(`/api/v1/admin/users/promote`, { method: "POST", body: { email } });
        } else if (role === "user" && origRole !== "user") {
          await fetchJSON(`/api/v1/admin/users/demote`, { method: "POST", body: { email } });
        }
      }
      setEditOpen(false);
      setEditUser(null);
      await load({ nextOffset: offset, search: q, tier: tierFilter });
    } catch (e) {
      alert(e.message || "Failed to save changes");
    } finally {
      setBusyEmail("");
    }
  };

  // --- bulk selection -------------------------------------------------------
  const toggleRow = (userId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(userId) ? next.delete(userId) : next.add(userId);
      return next;
    });
  };

  const pageIds = useMemo(() => rows.map((r) => String(r.id)), [rows]);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));

  const toggleAllOnPage = (checked) => {
    setSelected((prev) => {
      const next = new Set(prev);
      pageIds.forEach((id) => (checked ? next.add(id) : next.delete(id)));
      return next;
    });
  };

  const clearSelection = () => setSelected(new Set());

  // --- bulk actions ---------------------------------------------------------
  const requireSelected = (fn) => {
    if (selected.size === 0) {
      (window?.toast?.error ? window.toast.error : (m) => alert(m))("Select at least one user first.");
      return;
    }
    fn();
  };

  async function callBulk(op, extra = {}) {
    // Convert Set<string> -> List[int] so backend generates INTEGER comparison
    const user_ids = Array.from(selected).map((id) =>
      typeof id === "string" && /^\d+$/.test(id) ? Number(id) : id
    );
    if (user_ids.length === 0) return;

    const confirmMsg =
      op === "change_role"
        ? `Proceed with ${op} to '${extra.new_role}' for ${user_ids.length} user(s)?`
        : `Proceed with ${op} for ${user_ids.length} user(s)?`;
    if (!window.confirm(confirmMsg)) return;

    try {
      const res = await fetchJSON(`/api/v1/admin/users/bulk`, {
        method: "POST",
        body: {
          user_ids,
          op,
          ...extra,
          reason: bulkReason || undefined,
        },
      });

      const ok = Number(res?.count_succeeded || 0);
      const requested = Number(res?.count_requested || user_ids.length);
      const failed = Math.max(0, requested - ok);
      (window?.toast?.success ? window.toast.success : (m) => alert(m))(
        `${op}: ${ok} ok, ${failed} failed`
      );
      clearSelection();
      setBulkReason("");
      await load({ nextOffset: offset, search: q, tier: tierFilter });
    } catch (e) {
      (window?.toast?.error ? window.toast.error : (m) => alert(m))(
        e.message || "Bulk action failed"
      );
    }
  }

  // --- misc -----------------------------------------------------------------
  const countText = useMemo(
    () => (rows.length ? `${rows.length} row${rows.length > 1 ? "s" : ""}` : "—"),
    [rows.length]
  );

  // --- render ---------------------------------------------------------------
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Users</h2>
      </div>

      {/* Bulk actions bar — always visible */}
      <div className="flex flex-wrap items-center gap-2 p-3 rounded-lg bg-gray-50 border border-gray-200">
        <div className="text-sm">
          <b>{selectedCount}</b> selected
        </div>

        <button
          className="px-3 py-1.5 rounded bg-black text-white disabled:opacity-50"
          disabled={selectedCount === 0}
          onClick={() => requireSelected(() => callBulk("reset_password"))}
          title={selectedCount === 0 ? "Select at least one user" : "Send reset password emails"}
        >
          Reset Password
        </button>

        <button
          className="px-3 py-1.5 rounded bg-red-600 text-white disabled:opacity-50"
          disabled={selectedCount === 0}
          onClick={() => requireSelected(() => callBulk("deactivate"))}
          title={selectedCount === 0 ? "Select at least one user" : "Deactivate selected users"}
        >
          Deactivate
        </button>

        <button
          className="px-3 py-1.5 rounded bg-green-600 text-white disabled:opacity-50"
          disabled={selectedCount === 0}
          onClick={() => requireSelected(() => callBulk("reactivate"))}
          title={selectedCount === 0 ? "Select at least one user" : "Reactivate selected users"}
        >
          Reactivate
        </button>

        {/* intentional gap between Reactivate and role controls */}
        <div className="ml-4 flex items-center gap-2">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={bulkRole}
            onChange={(e) => setBulkRole(e.target.value)}
            title="New role"
          >
            {allowedRoles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            className="px-3 py-1.5 rounded bg-gray-800 text-white disabled:opacity-50"
            disabled={selectedCount === 0}
            onClick={() => requireSelected(() => callBulk("change_role", { new_role: bulkRole }))}
            title={selectedCount === 0 ? "Select at least one user" : `Change role to ${bulkRole}`}
          >
            Change Role
          </button>
        </div>

        <div className="flex-1" />

        <input
          className="border rounded px-2 py-1 text-sm w-64"
          placeholder="Reason (optional, saved to audit)"
          value={bulkReason}
          onChange={(e) => setBulkReason(e.target.value)}
        />
        <button className="text-sm underline" onClick={clearSelection}>
          Clear selection
        </button>
      </div>

      {/* Search / filter toolbar */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <input
            className="border rounded px-3 py-2 w-72"
            placeholder="Search email or name"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onSearchKey}
          />
          <button onClick={onSearch} className="px-3 py-2 rounded border" disabled={loading}>
            Search
          </button>
          {(q || tierFilter) && (
            <button onClick={clearFilters} className="px-3 py-2 rounded border">
              Clear
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={tierFilter}
            onChange={(e) => onTierFilterChange(e.target.value)}
            title="Filter by tier"
          >
            <option value="">All tiers</option>
            <option value="free">Free</option>
            <option value="mini">Mini+</option>
            <option value="pro">Pro</option>
          </select>
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
            className="px-3 py-2 rounded border"
            disabled={loading}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}

      {/* table */}
      <div className="overflow-auto border rounded">
        <table className="min-w-[1200px] w-full">
          <thead>
            <tr className="text-left text-sm text-gray-600">
              <th className="p-2 w-10">
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={(e) => toggleAllOnPage(e.target.checked)}
                  title="Select all on this page"
                />
              </th>
              <th className="p-2">Email</th>
              <th className="p-2">Name</th>
              <th className="p-2">Tier</th>
              <th className="p-2">Role</th>
              <th className="p-2">Status</th>
              <th className="p-2">Signup</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 &&
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={`sk-${i}`} className="border-t animate-pulse">
                  <td className="p-2"><div className="h-5 w-5 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-4 w-48 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-4 w-32 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-5 w-28 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-5 w-24 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-5 w-20 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-4 w-40 bg-zinc-200 rounded" /></td>
                  <td className="p-2"><div className="h-8 w-28 bg-zinc-200 rounded" /></td>
                </tr>
              ))}

            {rows.map((u) => {
              const id = String(u.id);
              const email = u.email;
              const role = String(u.role || "user");
              const tier = String(u.tier || "free").toLowerCase();
              const status = String(u.status || "active").toLowerCase();
              const disabled = busyEmail === email;

              return (
                <tr key={id} className="border-t">
                  <td className="p-2">
                    <input
                      type="checkbox"
                      checked={selected.has(id)}
                      onChange={() => toggleRow(id)}
                      title={`Select ${email}`}
                    />
                  </td>
                  <td className="p-2">{email}</td>
                  <td className="p-2">{u.name || "—"}</td>
                  <td className="p-2">
                    <Pill tone={tierTone(tier)}>{tier === "mini" ? "mini+" : tier}</Pill>
                  </td>
                  <td className="p-2">
                    <Pill tone={roleTone(role)}>{role}</Pill>
                  </td>
                  <td className="p-2">
                    <Pill tone={statusTone(status)}>{status}</Pill>
                  </td>
                  <td className="p-2">{fmtDate(u.created_at)}</td>
                  <td className="p-2 flex items-center gap-2">
                    <button
                      className="px-2 py-1 text-sm rounded border hover:bg-zinc-50 disabled:opacity-50"
                      disabled={disabled}
                      onClick={() => { setEditUser(u); setEditOpen(true); }}
                      title="Change tier/role (single)"
                    >
                      Change
                    </button>
                    <button
                      disabled={disabled}
                      onClick={() => logoutAll(email)}
                      className="px-2 py-1 text-sm rounded border hover:bg-red-50"
                      title="Force logout all sessions"
                    >
                      Logout all
                    </button>
                  </td>
                </tr>
              );
            })}

            {!rows.length && !loading && (
              <tr>
                <td className="p-4 text-sm text-gray-500" colSpan={8}>
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination total={total} limit={limit} offset={offset} onPageChange={onPageChange} />
      <div className="text-xs text-gray-500">{countText}</div>

      {/* Edit Modal (single-user) */}
      <Modal
        open={editOpen}
        user={editUser}
        onClose={() => { setEditOpen(false); setEditUser(null); }}
        onSave={applyChanges}
      />
    </div>
  );
}
