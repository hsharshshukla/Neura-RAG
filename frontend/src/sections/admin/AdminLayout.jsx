// ============================
// File: src/sections/admin/AdminLayout.jsx
// ============================
import { Outlet, NavLink } from 'react-router-dom';

const nav = [
  { to: '/admin', label: 'Overview', end: true },
  { to: '/admin/users', label: 'Users' },
  { to: '/admin/files', label: 'Files & Vector' },
  { to: '/admin/sessions', label: 'Chat Sessions' },
  { to: '/admin/billing', label: 'Billing' },
  { to: '/admin/coupons', label: 'Coupons' },   
  { to: '/admin/analytics', label: 'Analytics' },
  { to: '/admin/settings', label: 'Settings' },
];

export default function AdminLayout() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-10 bg-white border-b">
        <div className="max-w-[1400px] mx-auto px-4 h-14 flex items-center justify-between">
          <div className="font-black">Neura • Admin</div>
          <div className="flex gap-2 items-center w-full max-w-md">
            <input className="flex-1 rounded-xl border px-3 py-2 text-sm" placeholder="Search users, sessions, files…" />
            <button className="rounded-xl border px-3 py-2 text-sm">Notifications</button>
            <div className="w-8 h-8 rounded-full bg-gray-200" />
          </div>
        </div>
        <div className="bg-gray-50 border-t">
          <nav className="max-w-[1400px] mx-auto px-4 h-10 flex items-center gap-2 overflow-x-auto">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-sm ${isActive ? 'bg-white border border-gray-200' : 'hover:bg-white hover:border hover:border-gray-200'}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="max-w-[1400px] mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
