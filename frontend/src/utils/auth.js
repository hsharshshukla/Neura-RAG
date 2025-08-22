// src/utils/auth.js
import secureAxios from './secureAxios';

const AUTH_FLAG = 'authed';

function capFirst(s = '') {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function normRole(role) {
  const r = String(role || 'user').toLowerCase();
  return ['user', 'admin'].includes(r) ? r : 'user';
}

function normTier(tier) {
  const t = String(tier || 'free').toLowerCase();
  return ['free', 'pro'].includes(t) ? t : 'free';
}

// Persist minimal profile for UI and broadcast an auth change.
// Accepts optional { email, name, role, tier, token }.
export function markAuthed(profile = {}) {
  try {
    const email = (profile.email || '').trim();
    const name  = (profile.name  || '').trim();
    const role  = normRole(profile.role);
    const tier  = normTier(profile.tier);
    const plan  = capFirst(tier); // "Free" | "Pro"

    localStorage.setItem(AUTH_FLAG, '1');
    localStorage.setItem('email', email);
    localStorage.setItem('name',  name);
    localStorage.setItem('role',  role);
    localStorage.setItem('tier',  tier);
    localStorage.setItem('plan',  plan);

    // If backend sometimes returns a token, keep legacy compatibility
    if (profile.token) {
      localStorage.setItem('token', String(profile.token));
    }
  } catch {
    // no-op
  }
  try {
    window.dispatchEvent(new Event('auth-changed'));
  } catch {
    // no-op
  }
}

export function clearAuthed() {
  try {
    [
      AUTH_FLAG,
      'token', 'email', 'name', 'role', 'tier', 'plan',
      'active_chat_id', 'needs_reconsent'
    ].forEach(k => localStorage.removeItem(k));
  } catch {
    // no-op
  }
  try {
    window.dispatchEvent(new Event('auth-changed'));
  } catch {
    // no-op
  }
}

export async function logout() {
  try { await secureAxios.post('/auth/logout'); } catch {}
  clearAuthed();
}

export function isLoggedIn() {
  try {
    return localStorage.getItem(AUTH_FLAG) === '1' || !!localStorage.getItem('email');
  } catch {
    return false;
  }
}

export function getRole() {
  try { return (localStorage.getItem('role') || 'user').toLowerCase(); }
  catch { return 'user'; }
}

export function isAdmin() {
  return getRole() === 'admin';
}

export function getTier() {
  try { return (localStorage.getItem('tier') || 'free').toLowerCase(); }
  catch { return 'free'; }
}

export function getPlan() {
  try { return localStorage.getItem('plan') || capFirst(getTier()); }
  catch { return 'Free'; }
}

export function getEmail() {
  try { return localStorage.getItem('email') || ''; }
  catch { return ''; }
}

export function getName() {
  try { return localStorage.getItem('name') || ''; }
  catch { return ''; }
}

// ---- Legacy shim so older code that imports getToken still compiles ----
export function getToken() {
  try { return localStorage.getItem('token') || ''; }
  catch { return ''; }
}
