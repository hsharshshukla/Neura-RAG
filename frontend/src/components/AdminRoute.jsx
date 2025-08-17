// src/components/AdminRoute.jsx
import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import secureAxios from '../utils/secureAxios';
import { markAuthed, clearAuthed } from '../utils/auth';

const AdminRoute = ({ children }) => {
  const [checking, setChecking] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    let alive = true;

    (async () => {
      try {
        // Cookie-based check: 200 returns profile, 401 means not logged in
        const { data } = await secureAxios.get('/auth/me');
        if (!alive) return;

        // Persist minimal profile for UI (role/tier/name/email)
        markAuthed({
          email: data.email || '',
          name:  data.name  || '',
          role:  data.role  || 'user',
          tier:  data.tier  || 'free',
        });

        // Only admins allowed here
        if ((data.role || '').toLowerCase() !== 'admin') {
          navigate('/chat', { replace: true });
          return;
        }

        setChecking(false);
      } catch {
        // 401 or network -> bounce to login, preserving "next"
        clearAuthed();
        const next = location.pathname + location.search;
        navigate('/login?next=' + encodeURIComponent(next), { replace: true });
      }
    })();

    return () => { alive = false; };
  }, [navigate, location]);

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="text-gray-500 animate-pulse text-lg">Checking admin access…</div>
      </div>
    );
  }

  return <>{children}</>;
};

export default AdminRoute;
