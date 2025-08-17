// src/components/ScopeBadge.jsx
export default function ScopeBadge({ tier, className = "" }) {
  const t = (tier || "free").toLowerCase();
  const sessionScoped = t === "free" || t === "mini";
  const label = sessionScoped ? "Searching: This session" : "Searching: All documents";
  const style = sessionScoped
    ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
    : "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";

  return (
    <span
      className={`inline-flex items-center rounded-lg px-2.5 py-1 text-xs font-medium ${style} ${className}`}
      title={sessionScoped ? "Search uses only this chat session" : "Search spans all your documents"}
    >
      {label}
    </span>
  );
}
