// src/components/PlanBadge.jsx
export default function PlanBadge({ tier }) {
    const t = (tier || "free").toLowerCase();
    const sessionScoped = t === "free" || t === "mini";
    const scope = sessionScoped ? "This session" : "All documents";
  
    return (
      <div className="flex items-center gap-2">
        <span className="text-[10px] px-2 py-0.5 rounded bg-gray-100 text-gray-700 border">
          {t.toUpperCase()}
        </span>
        <span
          className={`text-[10px] px-2 py-0.5 rounded border ${
            sessionScoped
              ? "bg-amber-50 text-amber-700 border-amber-200"
              : "bg-emerald-50 text-emerald-700 border-emerald-200"
          }`}
          title={sessionScoped ? "Search uses only this chat session" : "Search spans all your documents"}
        >
          Searching: {scope}
        </span>
      </div>
    );
  }
  