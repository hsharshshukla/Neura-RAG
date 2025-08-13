// Simple, webpack-friendly env loader
const fromWindow = (typeof window !== "undefined" && window.__ENV__) || {};

export const ENV = {
  // webpack/CRA-style env (define in .env or build system)
  API_BASE_URL:
    process.env.REACT_APP_API_BASE_URL ||
    fromWindow.API_BASE_URL ||
    "http://127.0.0.1:8000/api/v1",

  // add other keys you were reading via import.meta.env.* here:
  // LEMON_PUBLIC_KEY:
  //   process.env.REACT_APP_LEMON_PUBLIC_KEY || fromWindow.LEMON_PUBLIC_KEY || "",
};
