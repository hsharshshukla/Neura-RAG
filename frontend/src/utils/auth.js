// src/utils/auth.js

const TOKEN_KEYS = ['token', 'authToken', 'access_token'];

export const getToken = () => {
  for (const k of TOKEN_KEYS) {
    const v = localStorage.getItem(k);
    if (v) return v;
  }
  return '';
};

export const setToken = (token) => {
  if (!token) return;
  localStorage.setItem('token', token);
  TOKEN_KEYS.filter(k => k !== 'token').forEach(k => localStorage.removeItem(k));
};

export const getRole    = () => (localStorage.getItem('role') || 'user').toLowerCase();
export const setRole    = (role) => role && localStorage.setItem('role', role);
export const getEmail   = () => localStorage.getItem('email') || '';
export const getPlan    = () => localStorage.getItem('plan') || 'Free';
export const isLoggedIn = () => Boolean(getToken() || getEmail());
export const isAdmin    = () => getRole() === 'admin';
export const isAuthed   = isLoggedIn; // back-compat

export const logout = () => {
  [...TOKEN_KEYS, 'email', 'name', 'plan', 'tier', 'role', 'needs_reconsent'].forEach(k => localStorage.removeItem(k));
};
