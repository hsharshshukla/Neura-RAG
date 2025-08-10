// src/pages/OAuthCallback.jsx
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export default function OAuthCallback() {
  const nav = useNavigate();
  useEffect(() => {
    // Prefer fragment first (#token=...), else try query (?token=...)
    const frag = new URLSearchParams(window.location.hash.slice(1));
    let token = frag.get('token');

    if (!token) {
      const query = new URLSearchParams(window.location.search);
      token = query.get('token');
    }

    if (token) {
      localStorage.setItem('token', token);
      nav('/'); // go to app home (protected)
    } else {
      // No token received -> back to login
      nav('/login');
    }
  }, [nav]);

  return <div className="p-8 text-center">Signing you in…</div>;
}
