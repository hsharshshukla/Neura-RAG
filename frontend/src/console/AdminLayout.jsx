// src/console/AdminLayout.jsx
import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";

const NAV = [
  { to: "/console/overview", label: "Overview" },
  { to: "/console/users", label: "Users" },
  { to: "/console/files", label: "Files" },
  { to: "/console/sessions", label: "Sessions" },
  { to: "/console/coupons", label: "Coupons" },
  { to: "/console/billing", label: "Billing" },
  { to: "/console/chat-analytics", label: "Chat Analytics" },
  { to: "/console/bulk-upload", label: "Bulk Upload" },
];

export default function AdminLayout() {
  const [workerHealthy, setWorkerHealthy] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/v1/admin/health");
        setWorkerHealthy(res.ok);
      } catch {
        setWorkerHealthy(false);
      }
    })();
  }, []);

  return (
    <div className="min-h-screen grid grid-cols-[240px_1fr] text-gray-900">
      {/* Sidebar */}
      <aside className="border-r bg-gray-50">
        <div className="p-4">
          <div className="text-lg font-semibold">Neura Console</div>
          <div className="text-xs text-gray-500">/console</div>
        </div>
        <nav className="px-2">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-lg mb-1 hover:bg-gray-100 ${
                  isActive ? "bg-gray-200 font-medium" : ""
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-4 px-3 pb-4 text-xs text-gray-500">
          <div className="h-px bg-gray-200 my-2" />
          <div>v1 console</div>
        </div>
      </aside>

      {/* Main */}
      <main className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-semibold">Console</h1>
          <span
            className={`text-xs px-2 py-1 rounded ${
              workerHealthy === null
                ? "bg-gray-100 text-gray-600"
                : workerHealthy
                ? "bg-green-100 text-green-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            {workerHealthy === null
              ? "Checking workers…"
              : workerHealthy
              ? "Workers: OK"
              : "Workers: Issues"}
          </span>
        </div>
        <Outlet />
      </main>
    </div>
  );
}
