// src/utils/auth.js
/**
 * Client-side auth helpers using a simple 'authed' flag.
 * We broadcast 'auth-changed' so the UI (TopBar, etc.) updates instantly.
 */
const AUTH_FLAG = 'authed';

export const markAuthed = () => {
  try { localStorage.setItem(AUTH_FLAG, '1'); } catch {}
  try { window.dispatchEvent(new Event('auth-changed')); } catch {}
};

export const clearAuthed = () => {
  try { localStorage.removeItem(AUTH_FLAG); } catch {}
  try { window.dispatchEvent(new Event('auth-changed')); } catch {}
};

export const isLoggedIn = () => {
  try { return localStorage.getItem(AUTH_FLAG) === '1'; } catch { return false; }
};

export const getRole = () => {
  try { return (localStorage.getItem('role') || 'user').toLowerCase(); } catch { return 'user'; }
};

export const isAdmin = () => getRole() === 'admin';

export const logout = () => {
  try {
    // legacy + profile keys
    localStorage.removeItem('token');
    localStorage.removeItem('email');
    localStorage.removeItem('name');
    localStorage.removeItem('role');
    localStorage.removeItem('tier');
    localStorage.removeItem('plan');
    localStorage.removeItem('active_chat_id');
  } catch {}
  clearAuthed(); // also dispatches 'auth-changed'
};

// ---- Legacy shim so older code that imports getToken still compiles ----
export const getToken = () => {
  try { return localStorage.getItem('token') || ''; } catch { return ''; }
};
