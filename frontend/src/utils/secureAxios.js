// src/utils/secureAxios.js
import axios from 'axios';
import { getToken } from './auth';

const API_BASE =
  (window.__API_BASE__ || process.env.REACT_APP_API_BASE || 'http://127.0.0.1:8000') + '/api/v1';

const secureAxios = axios.create({
  baseURL: API_BASE,
  withCredentials: false,
});

secureAxios.interceptors.request.use((config) => {
  if (!config.url) {
    // dev hint only
  }
  // Guard: if someone passes '/api/v1/...' by mistake, strip it.
  if (typeof config.url === 'string' && config.url.startsWith('/api/v1/')) {
    config.url = config.url.replace(/^\/api\/v1/, '');
  }
  const token = getToken();
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = 'Bearer ' + token;
  }
  return config;
});

secureAxios.interceptors.response.use(
  function (res) { return res; },
  function (err) {
    var status = err && err.response && err.response.status;
    if (status === 401) {
      localStorage.removeItem('token');
      var here = window.location.pathname + window.location.search;
      if (window.location.pathname.indexOf('/login') !== 0) {
        window.location.assign('/login?next=' + encodeURIComponent(here));
      }
    } else if (status === 403) {
      // keep user on the page; show UI error if desired
    }
    return Promise.reject(err);
  }
);

export default secureAxios;

