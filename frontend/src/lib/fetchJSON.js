// src/lib/fetchJSON.js
function isPlainObject(v) {
  return v && typeof v === "object" && !Array.isArray(v) && !(v instanceof FormData) && !(v instanceof Blob);
}

export async function fetchJSON(url, opts = {}) {
  const { headers: hdrs = {}, ...rest } = opts || {};
  const headers = new Headers(hdrs);

  const method = (rest.method || "GET").toUpperCase();

  let body = rest.body;
  const hasExplicitContentType = headers.has("Content-Type") || headers.has("content-type");

  if (body != null && isPlainObject(body) && !hasExplicitContentType) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }

  const res = await fetch(url, { ...rest, method, headers, body });

  if (res.status === 204) return null;

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (res.ok) {
    return isJson ? res.json() : res.text();
  }

  let message = `${res.status} ${res.statusText}`;
  try {
    if (isJson) {
      const err = await res.json();
      message = err?.detail || err?.message || JSON.stringify(err);
    } else {
      const txt = await res.text();
      try {
        const j = JSON.parse(txt);
        message = j?.detail || j?.message || txt;
      } catch {
        message = txt || message;
      }
    }
  } catch {}

  const e = new Error(message || "Request failed");
  e.status = res.status;
  e.statusText = res.statusText;
  throw e;
}

export function postJSON(url, data = {}, opts = {}) {
  return fetchJSON(url, {
    ...opts,
    method: "POST",
    body: opts.body ?? data,
  });
}
