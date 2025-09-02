// src/utils/secureAxios.js
import axios from "axios";
import { formatApiError } from "./formatApiError"; // same folder

/**
 * Resolve API base URL safely across toolchains.
 * 1) window.__API_BASE__ (runtime)
 * 2) import.meta.env.VITE_API_BASE (Vite)
 * 3) process.env.REACT_APP_API_BASE (CRA)
 * 4) '/api/v1' (same-origin default)
 */
function stripTrailingSlash(s) {
  return s && s.endsWith("/") ? s.slice(0, -1) : s;
}

const API_BASE = (() => {
  if (typeof window !== "undefined" && window.__API_BASE__) {
    return stripTrailingSlash(window.__API_BASE__);
  }
  if (
    typeof import.meta !== "undefined" &&
    import.meta.env &&
    typeof import.meta.env.VITE_API_BASE === "string" &&
    import.meta.env.VITE_API_BASE.length > 0
  ) {
    return stripTrailingSlash(import.meta.env.VITE_API_BASE);
  }
  if (
    typeof process !== "undefined" &&
    process.env &&
    typeof process.env.REACT_APP_API_BASE === "string" &&
    process.env.REACT_APP_API_BASE.length > 0
  ) {
    return stripTrailingSlash(process.env.REACT_APP_API_BASE);
  }
  return "/api/v1";
})();

// ---- Cookie helper (tiny, robust) ----
function readCookie(name) {
  const pair = document.cookie.split("; ").find((row) => row.startsWith(name + "="));
  if (!pair) return "";
  return decodeURIComponent(pair.split("=").slice(1).join("="));
}

const secureAxios = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  timeout: 20000,
});

// Debounce 401 notifications so multiple failing requests don’t trigger storms
let notified401Recently = false;
let notified401Timer = null;

secureAxios.interceptors.request.use((config) => {
  config.headers = config.headers || {};

  // Mark as XHR (helps some backends/caches)
  if (!config.headers["X-Requested-With"]) {
    config.headers["X-Requested-With"] = "XMLHttpRequest";
  }
  // Accept JSON by default
  if (!config.headers["Accept"]) {
    config.headers["Accept"] = "application/json";
  }

  // CSRF header (noop if cookie not present)
  const csrf = readCookie("csrf_token");
  if (csrf && !config.headers["X-CSRF-Token"]) {
    config.headers["X-CSRF-Token"] = csrf;
  }

  // Legacy bearer support (optional)
  try {
    const legacy = localStorage.getItem("token");
    if (legacy && legacy !== "null" && legacy !== "undefined") {
      config.headers.Authorization = "Bearer " + legacy;
    }
  } catch {}

  return config;
});

function normalizeAndReject(err) {
  const status = err?.response?.status;
  const data = err?.response?.data;
  const message = formatApiError(err);
  const e = new Error(message);
  e.status = status;
  e.data = data;
  return Promise.reject(e);
}

secureAxios.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;

    if (status === 401) {
      // Clear any legacy token and broadcast auth change once
      try {
        localStorage.removeItem("token");
      } catch {}
      if (!notified401Recently) {
        notified401Recently = true;
        try {
          window.dispatchEvent(new Event("auth-changed"));
        } catch {}
        if (notified401Timer) clearTimeout(notified401Timer);
        notified401Timer = setTimeout(() => {
          notified401Recently = false;
        }, 1500);
      }
      return normalizeAndReject(err);
    }

    if (status === 429) {
      const msg = formatApiError(err);
      try {
        window.dispatchEvent(new CustomEvent("rate-limit-hit", { detail: msg }));
      } catch {}
      if (window?.toast?.error) {
        window.toast.error(msg);
      } else {
        alert(msg);
      }
      return normalizeAndReject(err);
    }

    return normalizeAndReject(err);
  }
);

// Optional helper
secureAxios.ping = async () => {
  try {
    return (await secureAxios.get("/auth/me")).data;
  } catch {
    return null;
  }
};

export default secureAxios;
