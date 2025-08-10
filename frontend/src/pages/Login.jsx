// src/pages/login.jsx
import React, { useState } from 'react';
import secureAxios from '../utils/secureAxios';

const API_BASE = import.meta?.env?.VITE_API_BASE || 'http://127.0.0.1:8000';
const GOOGLE_ENABLED = (import.meta?.env?.VITE_GOOGLE_ENABLED === '1');
const APPLE_ENABLED  = (import.meta?.env?.VITE_APPLE_ENABLED === '1');

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const login = async () => {
    try {
      const params = new URLSearchParams();
      params.append('email', email);
      params.append('password', password);

      const res = await secureAxios.post('/auth/login', params, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });

      if (res.data?.access_token) {
        localStorage.setItem('email', res.data.email || email);
        localStorage.setItem('tier', res.data.tier || 'free');
        localStorage.setItem('token', res.data.access_token);
        window.location.href = '/chat';
      } else {
        setError('Invalid login response');
      }
    } catch (err) {
      const data = err?.response?.data;
      let message = 'Login failed';
      if (typeof data === 'string') {
        message = data;
      } else if (data?.detail) {
        if (Array.isArray(data.detail)) {
          message = data.detail.map(e => e.msg || JSON.stringify(e)).join(', ');
        } else if (typeof data.detail === 'string') {
          message = data.detail;
        }
      } else if (err?.message) {
        message = err.message;
      }
      console.error('Login failed:', data || err);
      setError(message);
    }
  };

  // Keep handlers (they won't render unless flags enabled)
  const goGoogle = () => {
    window.location.href = `${API_BASE}/api/v1/auth/google/start`;
  };
  const goApple = () => {
    window.location.href = `${API_BASE}/api/v1/auth/apple/start`;
  };

  const showSSO = GOOGLE_ENABLED || APPLE_ENABLED;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white shadow-lg rounded px-8 py-6 w-full max-w-md">
        <h2 className="text-2xl font-semibold mb-4 text-center">Login to Neura</h2>

        {error && (
          <div className="bg-red-100 text-red-700 px-4 py-2 rounded mb-4">
            {error}
          </div>
        )}

        {/* Email / Password */}
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="Email"
          className="w-full p-2 mb-3 border rounded"
          autoComplete="email"
        />
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          className="w-full p-2 mb-4 border rounded"
          autoComplete="current-password"
        />

        <button
          onClick={login}
          className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
        >
          Login
        </button>

        {/* Divider & Social buttons (hidden unless flags enabled) */}
        {showSSO && (
          <>
            <div className="flex items-center my-4">
              <div className="flex-1 h-px bg-gray-200" />
              <span className="px-3 text-xs text-gray-500">or</span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>

            {GOOGLE_ENABLED && (
              <button
                onClick={goGoogle}
                className="w-full border rounded py-2 hover:bg-gray-50 mb-2"
              >
                Continue with Google
              </button>
            )}

            {APPLE_ENABLED && (
              <button
                onClick={goApple}
                className="w-full border rounded py-2 hover:bg-gray-50"
              >
                Continue with Apple
              </button>
            )}
          </>
        )}

        {/* Register Link */}
        <div className="text-center mt-4">
          <span className="text-sm text-gray-600">
            Don’t have an account?{' '}
            <a href="/signup" className="text-blue-600 hover:underline">
              Register
            </a>
          </span>
        </div>
      </div>
    </div>
  );
};

export default Login;