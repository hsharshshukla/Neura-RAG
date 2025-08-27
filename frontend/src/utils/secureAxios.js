// src/utils/secureAxios.js
import axios from 'axios';

/**
 * Resolve API base URL safely across toolchains.
 * Order of precedence:
 *   1) window.__API_BASE__  (runtime override)
 *   2) import.meta.env.VITE_API_BASE  (Vite)
 *   3) process.env.REACT_APP_API_BASE (CRA / Webpack)
 *   4) '/api/v1' (same-origin default with FE proxy)
 */
const API_BASE = (() => {
  if (typeof window !== 'undefined' && window.__API_BASE__) {
    return stripTrailingSlash(window.__API_BASE__);
  }
  if (typeof import.meta !== 'undefined' &&
      import.meta.env &&
      typeof import.meta.env.VITE_API_BASE === 'string' &&
      import.meta.env.VITE_API_BASE.length > 0) {
    return stripTrailingSlash(import.meta.env.VITE_API_BASE);
  }
  if (typeof process !== 'undefined' &&
      process.env &&
      typeof process.env.REACT_APP_API_BASE === 'string' &&
      process.env.REACT_APP_API_BASE.length > 0) {
    return stripTrailingSlash(process.env.REACT_APP_API_BASE);
  }
  return '/api/v1';
})();

function stripTrailingSlash(s) {
  return s.endsWith('/') ? s.slice(0, -1) : s;
}

// ---- Cookie helper (tiny, robust) ----
function readCookie(name) {
  const pair = document.cookie.split('; ').find((row) => row.startsWith(name + '='));
  if (!pair) return '';
  return decodeURIComponent(pair.split('=').slice(1).join('='));
}

const secureAxios = axios.create({
  baseURL: API_BASE,       // All relative URLs prefix with this
  withCredentials: true,   // Send/receive HttpOnly cookies
  timeout: 20000,
});

// Debounce 401 notifications so multiple failing requests don’t trigger storms
let notified401Recently = false;
let notified401Timer = null;

secureAxios.interceptors.request.use((config) => {
  // Ensure headers object
  config.headers = config.headers || {};

  // Mark as XHR (helps some backends/caches)
  if (!config.headers['X-Requested-With']) {
    config.headers['X-Requested-With'] = 'XMLHttpRequest';
  }

  // Accept JSON by default
  if (!config.headers['Accept']) {
    config.headers['Accept'] = 'application/json';
  }

  // Don’t override Content-Type if caller set it (e.g., form urlencoded / FormData)
  // axios will set correct boundary for FormData automatically.
  // If you need JSON explicitly, set it per-call.

  // CSRF header (noop if cookie not present)
  const csrf = readCookie('csrf_token');
  if (csrf && !config.headers['X-CSRF-Token']) {
    config.headers['X-CSRF-Token'] = csrf;
  }

  // Legacy bearer support (optional)
  try {
    const legacy = localStorage.getItem('token');
    if (legacy && legacy !== 'null' && legacy !== 'undefined') {
      config.headers.Authorization = 'Bearer ' + legacy;
    }
  } catch {}

  return config;
});

secureAxios.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;

    if (status === 401) {
      // Clear any legacy token and broadcast auth change once
      try { localStorage.removeItem('token'); } catch {}
      if (!notified401Recently) {
        notified401Recently = true;
        try { window.dispatchEvent(new Event('auth-changed')); } catch {}
        if (notified401Timer) clearTimeout(notified401Timer);
        notified401Timer = setTimeout(() => { notified401Recently = false; }, 1500);
      }
      return Promise.reject(err);
    }

    if (status === 429) {
      const detail = err?.response?.data?.detail || 'Daily limit reached.';
      try { window.dispatchEvent(new CustomEvent('rate-limit-hit', { detail })); } catch {}
      if (window?.toast?.error) {
        window.toast.error(`${detail} Upgrade to Mini+ or Pro for unlimited chats.`);
      } else {
        alert(`${detail}\n\nUpgrade to Mini+ or Pro for unlimited chats.`);
      }
      return Promise.reject(err);
    }

    return Promise.reject(err);
  }
);

// Optional helper
secureAxios.ping = async () => {
  try { return (await secureAxios.get('/auth/me')).data; }
  catch { return null; }
};

export default secureAxios;
