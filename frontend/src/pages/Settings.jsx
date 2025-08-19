// pages/Settings.jsx
import React, { useEffect, useMemo, useState } from 'react';
import secureAxios from '../utils/secureAxios';

export default function SettingsPage() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [tier, setTier] = useState('free');

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState('info'); // 'success' | 'error' | 'info'
  const [busy, setBusy] = useState(false);

  // load profile
  useEffect(() => {
    (async () => {
      try {
        const { data } = await secureAxios.get('/user/profile');
        if (data?.email) setEmail(data.email);
        if (data?.name != null) setName(data.name || '');
        if (data?.plan) setTier((data.plan || '').toLowerCase());
      } catch {
        // optional: surface a silent error or toast
      }
    })();
  }, []);

  const canSubmit = useMemo(() => {
    if (busy) return false;
    if (!currentPassword || !newPassword || !confirmPassword) return false;
    if (newPassword !== confirmPassword) return false;
    if (newPassword.length < 8) return false;
    if (newPassword === currentPassword) return false;
    return true;
  }, [busy, currentPassword, newPassword, confirmPassword]);

  const setMsg = (type, text) => {
    setMessageType(type);
    setMessage(text);
  };

  const changePassword = async () => {
    // client-side validation (mirrors backend)
    if (!currentPassword || !newPassword || !confirmPassword) {
      setMsg('error', '❌ Please fill all password fields');
      return;
    }
    if (newPassword.length < 8) {
      setMsg('error', '❌ New password must be at least 8 characters');
      return;
    }
    if (newPassword === currentPassword) {
      setMsg('error', '❌ New password must be different from current password');
      return;
    }
    if (newPassword !== confirmPassword) {
      setMsg('error', '❌ Passwords do not match');
      return;
    }

    setBusy(true);
    setMessage('');
    try {
      await secureAxios.post('/auth/change-password', {
        currentPassword,
        newPassword,
        confirmPassword,
      });
      setMsg('success', '✅ Password changed. You may need to sign in again on other devices.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (e) {
      const detail = e?.response?.data?.detail || '❌ Failed to change password';
      setMsg('error', typeof detail === 'string' ? detail : '❌ Failed to change password');
    } finally {
      setBusy(false);
    }
  };

  const logoutAll = async () => {
    if (!confirm('Log out from all devices?')) return;
    setBusy(true);
    setMessage('');
    try {
      await secureAxios.post('/auth/logout-all');
      setMsg('success', '✅ Logged out from all devices');
      window.location.href = '/login';
    } catch {
      setMsg('error', '❌ Failed to logout everywhere');
    } finally {
      setBusy(false);
    }
  };

  const messageClass =
    messageType === 'success'
      ? 'bg-green-100 text-green-700'
      : messageType === 'error'
      ? 'bg-red-100 text-red-700'
      : 'bg-blue-100 text-blue-700';

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Account</h2>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Name</label>
            <input
              value={name || '—'}
              readOnly
              disabled
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-600"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Email</label>
            <input
              value={email || '—'}
              readOnly
              disabled
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-600"
            />
          </div>
        </div>
        <div className="mt-3 text-xs text-gray-500">
          Plan: <span className="uppercase font-medium">{tier}</span>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Security</h2>

        <div className="grid sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Current Password</label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3"
              autoComplete="current-password"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">New Password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3"
              autoComplete="new-password"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">Confirm Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3"
              autoComplete="new-password"
            />
          </div>

          <div className="sm:col-span-3 flex items-end">
            <button
              onClick={changePassword}
              disabled={!canSubmit}
              className="w-full bg-gradient-to-r from-teal-500 to-indigo-500 text-white px-4 py-2 rounded-xl shadow disabled:opacity-60"
            >
              {busy ? 'Working…' : 'Update Password'}
            </button>
          </div>
        </div>

        <div className="mt-4">
          <button
            onClick={logoutAll}
            disabled={busy}
            className="px-4 py-2 rounded-xl border border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            {busy ? 'Working…' : 'Logout from all devices'}
          </button>
        </div>
      </div>

      {message && (
        <div className={`${messageClass} px-4 py-2 rounded`}>
          {message}
        </div>
      )}
    </div>
  );
}
