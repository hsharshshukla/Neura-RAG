// frontend/src/utils/formatApiError.js
export function formatApiError(err) {
    try {
      const status = err?.response?.status;
      const data = err?.response?.data;
  
      // Common FastAPI / Axios shapes
      const fromData =
        (typeof data === 'string' && data) ||
        data?.message ||
        data?.detail ||
        (Array.isArray(data?.errors) && data.errors.map(e => e.msg || e.message).join('; ')) ||
        data?.error ||
        null;
  
      const base = fromData || err?.message || 'Request failed';
  
      if (!status) return base;
  
      // Add status context if present
      return `${base} (HTTP ${status})`;
    } catch {
      return err?.message || 'Request failed';
    }
  }
  