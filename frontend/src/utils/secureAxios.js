// src/utils/secureAxios.js
import axios from 'axios';

// Resolve API base dynamically (window override > Vite > CRA > default)
const API_BASE =
  (typeof window !== 'undefined' && window.__API_BASE__) ||
  (import.meta?.env?.VITE_API_BASE) ||
  (process?.env?.REACT_APP_API_BASE) ||
  '/api/v1';

// ---- Cookie helper ----
function readCookie(name) {
  const pair = document.cookie.split('; ').find((row) => row.startsWith(name + '='));
  if (!pair) return '';
  return decodeURIComponent(pair.split('=').slice(1).join('='));
}

const secureAxios = axios.create({
  baseURL: API_BASE,        // relative paths will be prefixed with this
  withCredentials: true,    // send/receive HttpOnly cookies
  timeout: 20000,
});

// Mark when we’ve notified the app about auth loss to avoid storms
let notified401Recently = false;
let notified401Timer = null;

secureAxios.interceptors.request.use((config) => {
  // Do NOT rewrite URLs; axios handles absolute vs relative for us.
  // Ensure headers object
  config.headers = config.headers || {};

  // CSRF (noop if cookie absent)
  const csrf = readCookie('csrf_token');           // server sets this if you enable CSRF
  if (csrf) config.headers['X-CSRF-Token'] = csrf;

  // Mark XHR (helps some backends distinguish browser calls)
  config.headers['X-Requested-With'] = 'XMLHttpRequest';

  // Reasonable defaults
  if (!config.headers['Accept']) {
    config.headers['Accept'] = 'application/json';
  }
  // Keep Content-Type if caller already set (e.g., form-data)
  if (!config.headers['Content-Type'] && !(config.data instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
  }

  // Legacy bearer (only if stored token exists)
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

    // Emit a single debounced signal on 401 so pages can react (e.g., show login)
    if (status === 401) {
      try { localStorage.removeItem('token'); } catch {}
      if (!notified401Recently) {
        notified401Recently = true;
        window.dispatchEvent(new Event('auth-changed'));
        // cool-down to avoid loops if multiple requests fail together
        if (notified401Timer) clearTimeout(notified401Timer);
        notified401Timer = setTimeout(() => { notified401Recently = false; }, 1500);
      }
      return Promise.reject(err);
    }

    // Nice UX for rate limits (optional)
    if (status === 429) {
      const detail = err?.response?.data?.detail || 'Daily limit reached.';
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

// Optional helpers
secureAxios.ping = async () => {
  try { return (await secureAxios.get('/auth/me')).data; }
  catch { return null; }
};

export default secureAxios;
