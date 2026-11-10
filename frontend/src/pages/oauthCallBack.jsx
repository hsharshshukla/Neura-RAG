// src/pages/OAuthCallback.jsx
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import secureAxios from '../utils/secureAxios';
import { markAuthed } from '../utils/auth';

export default function OAuthCallback() {
  const nav = useNavigate();
  useEffect(() => {
    secureAxios.get('/auth/me').then(({ data }) => {
      if (!data?.authenticated) throw new Error('OAuth session was not established');
      markAuthed(data);
      nav('/chat', { replace: true });
    }).catch(() => nav('/login', { replace: true }));
  }, [nav]);

  return <div className="p-8 text-center">Signing you in…</div>;
}
