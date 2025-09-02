export function formatApiError(err: unknown): string {
    const data = (err as any)?.response?.data ?? (err as any)?.data ?? err;
  
    if (typeof data === "string") return data;
  
    if (data && typeof data === "object") {
      // FastAPI validation style
      const detail = (data as any).detail;
      if (Array.isArray(detail)) {
        return detail.map((d: any) => d?.msg || JSON.stringify(d)).join("; ");
      }
      if (typeof detail === "string") return detail;
      if ((data as any).message) return (data as any).message;
      try { return JSON.stringify(data); } catch { /* ignore */ }
    }
  
    return String(err ?? "Unknown error");
  }
  