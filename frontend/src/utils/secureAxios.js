// src/utils/secureAxios.js
import axios from 'axios';

// Same-origin base; the FE proxy will forward this to the real backend.
const API_BASE = '/api/v1';

const secureAxios = axios.create({
  baseURL: API_BASE,
  withCredentials: true, // send HttpOnly cookie
});

// ---- Simple cookie reader (no regex) ----
function readCookie(name) {
  // Find "name=<value>" pair among semicolon-separated cookies
  const pair = document.cookie.split('; ').find((row) => row.startsWith(name + '='));
  if (!pair) return '';
  // Handle values that may contain additional '=' characters
  return decodeURIComponent(pair.split('=').slice(1).join('='));
}

secureAxios.interceptors.request.use((config) => {
  // Guard: avoid double /api/v1 prefix if callers pass absolute paths.
  if (config && typeof config.url === 'string' && config.url.startsWith('/api/v1/')) {
    config.url = config.url.replace(/^\/api\/v1/, '');
  }

  // Attach CSRF token if present (safe even if CSRF not enabled yet)
  const csrf = readCookie('csrf_token');
  if (csrf) {
    config.headers = config.headers || {};
    config.headers['X-CSRF-Token'] = csrf;
  }

  // Legacy header support (only if a real token string exists)
  try {
    const legacyToken = localStorage.getItem('token');
    if (legacyToken && legacyToken !== 'null' && legacyToken !== 'undefined') {
      config.headers = config.headers || {};
      config.headers.Authorization = 'Bearer ' + legacyToken;
    }
  } catch {}

  return config;
});

secureAxios.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;
    if (status === 401) {
      try { localStorage.removeItem('token'); } catch {}
      window.dispatchEvent(new Event('auth-changed'));
      return Promise.reject(err);
    }

    if (status === 429) {
      const detail = err?.response?.data?.detail || 'Daily limit reached.';
      // Broadcast so pages can react if they want
      try {
        window.dispatchEvent(new CustomEvent('rate-limit-hit', { detail }));
      } catch {}

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

export default secureAxios;
