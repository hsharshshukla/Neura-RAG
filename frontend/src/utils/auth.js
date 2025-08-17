// src/utils/auth.js
import secureAxios from './secureAxios';

const AUTH_FLAG = 'authed';

// Persist minimal profile for UI and broadcast an auth change
export function markAuthed(profile = {}) {
  try {
    localStorage.setItem(AUTH_FLAG, '1');
    if (profile.email != null) localStorage.setItem('email', profile.email || '');
    if (profile.name  != null) localStorage.setItem('name',  profile.name  || '');
    if (profile.role  != null) localStorage.setItem('role',  String(profile.role || 'user').toLowerCase());
    if (profile.tier  != null) {
      const tier = String(profile.tier || 'free').toLowerCase();
      localStorage.setItem('tier', tier);
      localStorage.setItem('plan', tier === 'pro' ? 'Pro' : 'Free');
    }
  } catch {}
  try { window.dispatchEvent(new Event('auth-changed')); } catch {}
}

export function clearAuthed() {
  try {
    [
      AUTH_FLAG,
      'token', 'email', 'name', 'role', 'tier', 'plan',
      'active_chat_id', 'needs_reconsent'
    ].forEach(k => localStorage.removeItem(k));
  } catch {}
  try { window.dispatchEvent(new Event('auth-changed')); } catch {}
}

export async function logout() {
  try { await secureAxios.post('/auth/logout'); } catch {}
  clearAuthed();
}

export function isLoggedIn() {
  try { return localStorage.getItem(AUTH_FLAG) === '1' || !!localStorage.getItem('email'); }
  catch { return false; }
}

export function getRole() {
  try { return (localStorage.getItem('role') || 'user').toLowerCase(); }
  catch { return 'user'; }
}

export function isAdmin() { return getRole() === 'admin'; }

// ---- Legacy shim so older code that imports getToken still compiles ----
export function getToken() {
  try { return localStorage.getItem('token') || ''; } catch { return ''; }
}
