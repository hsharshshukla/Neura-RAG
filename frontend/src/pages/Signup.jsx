// src/pages/signup.jsx
import React, { useState } from 'react';
import secureAxios from '../utils/secureAxios';
import { markAuthed } from '../utils/auth';
import { useNavigate } from 'react-router-dom';

export default function Signup() {
  const navigate = useNavigate();

  const TOS_VERSION = '2025-08-01';
  const PRIVACY_VERSION = '2025-08-01';

  const [agree, setAgree] = useState(false);
  const [marketingOptIn, setMarketingOptIn] = useState(false);

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [showPw2, setShowPw2] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const strength = () => {
    let s = 0;
    if (pw.length >= 8) s++;
    if (/[A-Z]/.test(pw)) s++;
    if (/[a-z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return s;
  };

  const submit = async () => {
    if (loading) return; // prevent double submits
    setError('');

    const normalizedEmail = email.trim().toLowerCase();

    // Client-side checks
    if (!name.trim()) return setError('Please enter your name');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) return setError('Enter a valid email');
    if (pw !== pw2) return setError('Passwords do not match');
    if (strength() < 3) return setError('Use a stronger password (min 8 chars incl. mix)');
    if (!agree) return setError('Please accept Terms & Privacy to continue.');

    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('email', normalizedEmail);
      params.append('password', pw);
      params.append('name', name.trim());
      params.append('agree', String(agree));
      params.append('marketingOptIn', String(marketingOptIn));
      params.append('tosVersion', TOS_VERSION);
      params.append('privacyVersion', PRIVACY_VERSION);

      // Cookie-based signup: server sets HttpOnly cookie + returns profile
      const res = await secureAxios.post('/auth/signup', params, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });

      const d = res.data || {};

      // If backend sometimes returns a token, persist for legacy code
      if (d.access_token) localStorage.setItem('token', d.access_token);

      // Normalize tier/plan + seed minimal profile for UI
      const tier = String(d.tier || 'free').toLowerCase();
      markAuthed({
        email: d.email || normalizedEmail,
        name: d.name || name.trim(),
        role: d.role || 'user',
        tier,           // 'free' | 'pro'
        token: d.access_token, // optional
      });

      // Optional legacy: keep 'plan' in sync if some components still read it
      localStorage.setItem('plan', tier.charAt(0).toUpperCase() + tier.slice(1));

      // Go straight to chat after successful signup
      navigate('/chat', { replace: true });
    } catch (err) {
      const data = err?.response?.data;
      let message = 'Signup failed';
      if (typeof data === 'string') message = data;
      else if (data?.detail) {
        if (Array.isArray(data.detail)) message = data.detail.map(e => e.msg || JSON.stringify(e)).join(', ');
        else if (typeof data.detail === 'string') message = data.detail;
      } else if (err?.message) message = err.message;
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const strengthVal = strength();
  const strengthLabel = ['Too weak', 'Weak', 'Okay', 'Good', 'Strong', 'Very strong'][strengthVal];

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-teal-500 to-indigo-500" />
            <h1 className="text-xl font-semibold tracking-tight">Create your Neura account</h1>
          </div>

          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">
              {error}
            </div>
          )}

          <label className="block text-sm text-gray-700 mb-1">Full Name</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Your name"
            className="w-full p-3 rounded-xl border border-gray-200 mb-3 focus:outline-none focus:ring-2 focus:ring-teal-500"
            maxLength={80}
            autoComplete="name"
            disabled={loading}
          />

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
          <div className="relative mb-2">
            <input
              type={showPw ? 'text' : 'password'}
              value={pw}
              onChange={e => setPw(e.target.value)}
              placeholder="••••••••"
              className="w-full p-3 rounded-xl border border-gray-200 pr-12 focus:outline-none focus:ring-2 focus:ring-teal-500"
              autoComplete="new-password"
              disabled={loading}
            />
            <button
              type="button"
              onClick={() => setShowPw(s => !s)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50"
              disabled={loading}
            >
              {showPw ? 'Hide' : 'Show'}
            </button>
          </div>

          <div className="mb-3">
            <div className="w-full h-2 rounded bg-gray-200 overflow-hidden">
              <div
                className="h-2 transition-all"
                style={{
                  width: `${(strengthVal / 5) * 100}%`,
                  background:
                    strengthVal >= 4
                      ? '#16a34a'
                      : strengthVal >= 3
                      ? '#22c55e'
                      : strengthVal >= 2
                      ? '#f59e0b'
                      : '#ef4444',
                }}
              />
            </div>
            <div className="text-xs text-gray-500 mt-1">{strengthLabel}</div>
          </div>

          <label className="block text-sm text-gray-700 mb-1">Confirm Password</label>
          <div className="relative mb-4">
            <input
              type={showPw2 ? 'text' : 'password'}
              value={pw2}
              onChange={e => setPw2(e.target.value)}
              placeholder="••••••••"
              className="w-full p-3 rounded-xl border border-gray-200 pr-12 focus:outline-none focus:ring-2 focus:ring-teal-500"
              autoComplete="new-password"
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
              disabled={loading}
            />
            <button
              type="button"
              onClick={() => setShowPw2(s => !s)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50"
              disabled={loading}
            >
              {showPw2 ? 'Hide' : 'Show'}
            </button>
          </div>

          <label className="flex items-start gap-2 text-sm mt-3">
            <input
              type="checkbox"
              checked={agree}
              onChange={(e)=>setAgree(e.target.checked)}
              disabled={loading}
            />
            <span>
              I agree to the{' '}
              <a href="/terms" target="_blank" rel="noreferrer" className="text-teal-600 underline">Terms of Service</a>{' '}
              and{' '}
              <a href="/privacy" target="_blank" rel="noreferrer" className="text-teal-600 underline">Privacy Policy</a>.
            </span>
          </label>

          <label className="flex items-start gap-2 text-xs mt-2 text-gray-600">
            <input
              type="checkbox"
              checked={marketingOptIn}
              onChange={(e)=>setMarketingOptIn(e.target.checked)}
              disabled={loading}
            />
            <span>Send me product updates and tips (optional).</span>
          </label>

          <button
            onClick={submit}
            disabled={loading || !agree}
            className={`w-full mt-4 py-2.5 rounded-xl text-white shadow ${loading || !agree ? 'opacity-70 cursor-not-allowed' : 'hover:opacity-95'} bg-gradient-to-r from-teal-500 to-indigo-500`}
          >
            {loading ? 'Creating account…' : 'Create Account'}
          </button>

          <div className="text-center mt-4 text-sm text-gray-600">
            Already have an account?{' '}
            <a href="/login" className="text-teal-600 hover:underline">Login</a>
          </div>
        </div>
      </div>
    </div>
  );
}

