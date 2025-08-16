// src/components/AdminRoute.jsx
import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import secureAxios from '../utils/secureAxios';
import { isLoggedIn, isAdmin } from '../utils/auth';

const AdminRoute = ({ children }) => {
  const [checking, setChecking] = useState(true);
  const [allow, setAllow] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      // Quick local check first
      if (!isLoggedIn()) {
        if (mounted) { setAllow(false); setChecking(false); }
        return;
      }

      try {
        // Soft verify cookie session (no 401 spam; backend /auth/me returns authenticated:false)
        const { data } = await secureAxios.get('/auth/me');
        if (!mounted) return;
        if (!data?.authenticated) {
          setAllow(false);
        } else {
          const role = (data.role || localStorage.getItem('role') || 'user').toLowerCase();
          setAllow(role === 'admin' || isAdmin());
        }
      } catch {
        // Network error: fall back to local role only
        setAllow(isAdmin());
      } finally {
        if (mounted) setChecking(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  if (checking) return <div className="p-6 text-gray-500">Checking admin access…</div>;
  if (!allow) return <Navigate to="/login" replace />;

  return children;
};

export default AdminRoute;
