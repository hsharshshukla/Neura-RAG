// src/console/shared/StatCard.jsx
export default function StatCard({ label, value, hint }) {
  return (
    <div className="rounded-xl border p-4 bg-white dark:bg-zinc-900">
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint ? <div className="mt-1 text-xs text-zinc-400">{hint}</div> : null}
    </div>
  );
}
