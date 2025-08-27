// src/pages/Login.jsx
import React, { useState } from 'react';
import secureAxios from '../utils/secureAxios';
import { useLocation, useNavigate } from 'react-router-dom';
import { markAuthed } from '../utils/auth';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [unverifiedEmail, setUnverifiedEmail] = useState('');
  const [resendMsg, setResendMsg] = useState('');

  const location = useLocation();
  const navigate = useNavigate();

  const submit = async () => {
    if (loading) return;
    setError('');
    setResendMsg('');
    setUnverifiedEmail('');

    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail || !password) {
      setError('Please enter email and password');
      return;
    }

    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('email', normalizedEmail);
      params.append('password', password);

      const res = await secureAxios.post('/auth/login', params, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      const data = res.data || {};

      if (data.needs_reconsent) localStorage.setItem('needs_reconsent', '1');
      else localStorage.removeItem('needs_reconsent');

      markAuthed({
        email: data.email || normalizedEmail,
        name:  data.name  || '',
        role:  data.role  || 'user',
        tier:  data.tier  || 'free',
        token: data.access_token, // optional legacy
      });

      // On success: go where they were heading, or /chat.
      const urlParams = new URLSearchParams(location.search);
      const nextFromQuery = urlParams.get('next');
      const fromState = location.state?.from?.pathname;
      const dest = fromState || nextFromQuery || '/chat';
      if (location.pathname !== dest) navigate(dest, { replace: true });
    } catch (err) {
      const status = err?.response?.status;
      const data = err?.response?.data;
      let message = 'Login failed';
      if (typeof data === 'string') message = data;
      else if (data?.detail) {
        if (Array.isArray(data.detail)) message = data.detail.map(e => e.msg || JSON.stringify(e)).join(', ');
        else if (typeof data.detail === 'string') message = data.detail;
      } else if (err?.message) message = err.message;

      // Hard-gate unverified accounts
      if (status === 403 && /not verified/i.test(message)) {
        setUnverifiedEmail(normalizedEmail);
        navigate('/verify-sent', { state: { email: normalizedEmail } });
        setLoading(false);
        return;
      }

      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const resend = async () => {
    if (!unverifiedEmail) return;
    setResendMsg('');
    try {
      await secureAxios.post('/auth/resend-verification', { email: unverifiedEmail });
      setResendMsg('Verification email sent. Check your inbox.');
    } catch {
      setResendMsg('Could not send verification email. Try again.');
    }
  };

  const goGoogle = () => { window.location.href = `/api/v1/auth/google/start`; };
  const goApple  = () => { window.location.href = `/api/v1/auth/apple/start`; };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-teal-500 to-indigo-500" />
            <h1 className="text-xl font-semibold tracking-tight">Login to Neura</h1>
          </div>

          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">
              {error}
              {unverifiedEmail && (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={resend}
                    className="text-sm text-teal-600 hover:underline"
                    disabled={loading}
                  >
                    Resend verification email
                  </button>
                  {resendMsg && <div className="mt-1 text-gray-700">{resendMsg}</div>}
                </div>
              )}
            </div>
          )}

          <label className="block text-sm text-gray-700 mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full p-3 rounded-xl border border-gray-200 mb-3 focus:outline-none focus:ring-2 focus:ring-teal-500"
            autoComplete="email"
            disabled={loading}
          />

          <label className="block text-sm text-gray-700 mb-1">Password</label>
          <div className="relative mb-4">
            <input
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full p-3 rounded-xl border border-gray-200 pr-12 focus:outline-none focus:ring-2 focus:ring-teal-500"
              autoComplete="current-password"
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
              disabled={loading}
            />
            <button
              type="button"
              onClick={() => setShowPw(s => !s)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50"
              aria-label={showPw ? 'Hide password' : 'Show password'}
              disabled={loading}
            >
              {showPw ? 'Hide' : 'Show'}
            </button>
          </div>

          <div className="flex items-center justify-between mb-4 text-sm">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                className="rounded"
                onChange={(e) => {
                  if (e.target.checked) localStorage.setItem('remember', '1');
                  else localStorage.removeItem('remember');
                }}
                disabled={loading}
              />
              Remember me
            </label>
            <a href="/forgot" className="text-teal-600 hover:underline">Forgot password?</a>
          </div>

          <button
            onClick={submit}
            disabled={loading}
            className={`w-full py-2.5 rounded-xl text-white shadow ${loading ? 'opacity-70 cursor-not-allowed' : 'hover:opacity-95'} bg-gradient-to-r from-teal-500 to-indigo-500`}
          >
            {loading ? 'Signing in…' : 'Login'}
          </button>

          <div className="text-center mt-4 text-sm text-gray-600">
            Don’t have an account?{' '}
            <a href="/signup" className="text-teal-600 hover:underline">Register</a>
          </div>

          {/* Optional social:
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button onClick={goGoogle} className="border rounded p-2">Google</button>
            <button onClick={goApple}  className="border rounded p-2">Apple</button>
          </div>
          */}
        </div>
      </div>
    </div>
  );
}
