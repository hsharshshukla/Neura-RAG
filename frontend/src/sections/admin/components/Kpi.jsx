// ============================
// File: src/sections/admin/components/Kpi.jsx
// ============================
export default function Kpi({ label, value, hint }) {
    return (
      <div className="bg-white rounded-2xl p-4 border border-gray-200 shadow-sm">
        <div className="text-xs text-gray-500">{label}</div>
        <div className="text-2xl font-semibold mt-1">{value}</div>
        {hint && <div className="text-xs text-gray-400 mt-1">{hint}</div>}
      </div>
    );
  }