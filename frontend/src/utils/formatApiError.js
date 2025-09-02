// frontend/src/utils/formatApiError.js
export function formatApiError(err) {
  try {
    const status = err?.response?.status;
    const data = err?.response?.data;

    // Handle FastAPI/Pydantic validation arrays:
    if (Array.isArray(data?.detail)) {
      const msgs = data.detail.map((e) => {
        const loc = Array.isArray(e.loc) ? e.loc.join('.') : e.loc;
        return loc ? `${e.msg} [${loc}]` : e.msg;
      });
      return `${msgs.join('; ')}${status ? ` (HTTP ${status})` : ''}`;
    }

    // Common shapes
    const fromData =
      (typeof data === 'string' && data) ||
      data?.message ||
      (typeof data?.detail === 'string' && data.detail) ||
      (Array.isArray(data?.errors) && data.errors.map(e => e.msg || e.message).join('; ')) ||
      data?.error ||
      null;

    const base = fromData || err?.message || 'Request failed';
    return status ? `${base} (HTTP ${status})` : base;
  } catch {
    return err?.message || 'Request failed';
  }
}
