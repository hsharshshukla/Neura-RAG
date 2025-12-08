// src/console/shared/Bar.jsx
export default function Bar({ label, value = 0, max = 100 }) {
    const pct = Math.max(0, Math.min(100, max ? (value / max) * 100 : 0));
    return (
      <div>
        <div className="flex justify-between text-xs text-zinc-500 mb-1">
          <span>{label}</span>
          <span>{value}</span>
        </div>
        <div className="h-2 w-full bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-indigo-600 dark:bg-indigo-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    );
  }
  