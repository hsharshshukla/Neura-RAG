// src/utils/secureAxios.js
import axios from 'axios';
import { ENV } from "../config/env";

// const API_BASE = import.meta?.env?.VITE_API_BASE || 'http://127.0.0.1:8000';

// const secureAxios = axios.create({
//   // baseURL: `${API_BASE}/api/v1`,
//   baseURL:   API_BASE, 
//   withCredentials: false, // using Authorization header instead of cookies
//   // Don't set a global Content-Type; let Axios set it (JSON, form, multipart, etc.)
// });
const API_BASE =
  (window.__API_BASE__ || process.env.REACT_APP_API_BASE || 'http://127.0.0.1:8000') + '/api/v1';

const secureAxios = axios.create({ baseURL: API_BASE, withCredentials: false });

secureAxios.interceptors.request.use((config) => {
  if (!config.url) {
    console.trace('⚠️ secureAxios called with missing URL');
  }
  const token = localStorage.getItem('token');
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Optional: central 401 handling
secureAxios.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;
    if (status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('email');
      localStorage.removeItem('tier');
      if (window.location.pathname !== '/login') {
        window.location.assign('/login');
      }
    }
    return Promise.reject(err);
  }
);

export default secureAxios;

