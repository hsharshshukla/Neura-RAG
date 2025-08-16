// src/utils/secureAxios.js
import axios from 'axios';

const API_BASE =
  (window.__API_BASE__ || process.env.REACT_APP_API_BASE || 'http://127.0.0.1:8000') + '/api/v1';

const secureAxios = axios.create({
  baseURL: API_BASE,
  withCredentials: true, // ⬅️ send HttpOnly cookie across ports
});

secureAxios.interceptors.request.use((config) => {
  if (config && typeof config.url === 'string' && config.url.startsWith('/api/v1/')) {
    config.url = config.url.replace(/^\/api\/v1/, '');
  }

  // Legacy header support (won't exist in cookie mode, but harmless):
  try {
    const legacyToken = localStorage.getItem('token');
    if (legacyToken) {
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
      // Clear legacy token if present; don't hard-redirect here
      try { localStorage.removeItem('token'); } catch {}
      window.dispatchEvent(new Event('auth-changed'));
    }
    return Promise.reject(err);
  }
);

export default secureAxios;
