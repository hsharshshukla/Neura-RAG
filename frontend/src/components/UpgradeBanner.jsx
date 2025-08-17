// src/components/UpgradeBanner.jsx
import { useEffect, useState } from "react";

export default function UpgradeBanner() {
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const onRL = (e) => setMsg(e?.detail || "Daily limit reached.");
    window.addEventListener("rate-limit-hit", onRL);
    return () => window.removeEventListener("rate-limit-hit", onRL);
  }, []);

  if (!msg) return null;

  return (
    <div className="mt-2 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded px-3 py-2 flex items-center justify-between">
      <div>{msg} Upgrade to <strong>Mini+</strong> or <strong>Pro</strong> for unlimited chats.</div>
      <a
        href="/pricing"
        className="ml-3 inline-flex items-center text-amber-900 underline underline-offset-2 hover:opacity-80"
      >
        See plans
      </a>
    </div>
  );
}
