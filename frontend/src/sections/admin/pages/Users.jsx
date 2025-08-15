// ============================
// File: src/sections/admin/pages/Users.jsx
// ============================
import { useEffect, useState, useCallback } from 'react';
import secureAxios from '../../../utils/secureAxios';
import Card from '../components/Card';

const LIMIT = 20;

export default function Users() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState('');
  const [tier, setTier] = useState('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [busyEmail, setBusyEmail] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const { data } = await secureAxios.get('/admin/users', {
        params: { q, tier, limit: LIMIT, offset: 0 },
      });
      setRows(data.items || []);
      setUpdatedAt(new Date());
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || 'Failed to load users';
      setErr(msg);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [q, tier]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const onPromote = async (email) => {
    if (!window.confirm(`Promote ${email} to admin?`)) return;
    setBusyEmail(email);
    try {
      await secureAxios.post('/admin/users/promote', { email });
      await fetchUsers();
    } catch (e) {
      alert('Promote failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setBusyEmail(null);
    }
  };

  const onDemote = async (email) => {
    if (!window.confirm(`Demote ${email} to regular user?`)) return;
    setBusyEmail(email);
    try {
      await secureAxios.post('/admin/users/demote', { email });
      await fetchUsers();
    } catch (e) {
      alert('Demote failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setBusyEmail(null);
    }
  };

  const onSetTier = async (email, newTier) => {
    if (!window.confirm(`Set ${email} to "${newTier}" tier?`)) return;
    setBusyEmail(email);
    try {
      await secureAxios.post('/admin/users/set-tier', { email, tier: newTier });
      await fetchUsers();
    } catch (e) {
      alert('Set tier failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setBusyEmail(null);
    }
  };

  const onLogoutAll = async (email) => {
    if (!window.confirm(`Force logout for ${email}?`)) return;
    setBusyEmail(email);
    try {
      await secureAxios.post('/admin/users/logout-all', { email });
      await fetchUsers();
    } catch (e) {
      alert('Logout-all failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setBusyEmail(null);
    }
  };

  const fmtDate = (d) => {
    try { return d ? new Date(d).toISOString().slice(0, 10) : '-'; }
    catch { return '-'; }
  };

  return (
    <Card
      title="Users"
      action={
        <div className="flex items-center gap-2">
          <button
            onClick={fetchUsers}
            disabled={loading}
            className="text-sm px-3 py-1.5 rounded-lg border hover:bg-gray-50 disabled:opacity-60"
            title={updatedAt ? `Updated at ${updatedAt.toLocaleTimeString()}` : 'Refresh'}
          >
            Refresh{updatedAt ? ` · ${updatedAt.toLocaleTimeString()}` : ''}
          </button>
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="text-sm border rounded-lg px-2 py-1"
          >
            <option value="">All tiers</option>
            <option value="free">Free</option>
            <option value="pro">Pro</option>
          </select>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="text-sm border rounded-lg px-2 py-1"
            placeholder="Search…"
          />
        </div>
      }
    >
      {err && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">
          {err}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Name', 'Email', 'Role', 'Tier', 'Joined', 'Actions'].map((h) => (
                <th key={h} className="text-left px-3 py-2 font-medium text-gray-600">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                  Loading…
                </td>
              </tr>
            )}

            {!loading && rows.length === 0 && !err && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                  No users found.
                </td>
              </tr>
            )}

            {!loading &&
              rows.map((u) => {
                const isBusy = busyEmail === u.email;
                return (
                  <tr key={u.id || u.email} className="border-t">
                    <td className="px-3 py-2">{u.name || '-'}</td>
                    <td className="px-3 py-2 text-gray-600">{u.email}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-2 py-0.5 text-xs rounded-full ${
                          (u.role || 'user') === 'admin'
                            ? 'bg-amber-50 text-amber-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {u.role || 'user'}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-2 py-0.5 text-xs rounded-full ${
                          u.tier === 'pro'
                            ? 'bg-indigo-50 text-indigo-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {u.tier}
                      </span>
                    </td>
                    <td className="px-3 py-2">{fmtDate(u.created_at)}</td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-2">
                        {(u.role || 'user') !== 'admin' ? (
                          <button
                            onClick={() => onPromote(u.email)}
                            disabled={isBusy}
                            className="px-2 py-1 text-xs rounded-lg border hover:bg-gray-50 disabled:opacity-60"
                          >
                            Promote
                          </button>
                        ) : (
                          <button
                            onClick={() => onDemote(u.email)}
                            disabled={isBusy}
                            className="px-2 py-1 text-xs rounded-lg border hover:bg-gray-50 disabled:opacity-60"
                          >
                            Demote
                          </button>
                        )}
                        {u.tier === 'pro' ? (
                          <button
                            onClick={() => onSetTier(u.email, 'free')}
                            disabled={isBusy}
                            className="px-2 py-1 text-xs rounded-lg border hover:bg-gray-50 disabled:opacity-60"
                          >
                            Set Free
                          </button>
                        ) : (
                          <button
                            onClick={() => onSetTier(u.email, 'pro')}
                            disabled={isBusy}
                            className="px-2 py-1 text-xs rounded-lg border hover:bg-gray-50 disabled:opacity-60"
                          >
                            Set Pro
                          </button>
                        )}
                        <button
                          onClick={() => onLogoutAll(u.email)}
                          disabled={isBusy}
                          className="px-2 py-1 text-xs rounded-lg border hover:bg-gray-50 disabled:opacity-60"
                        >
                          Logout All
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}



