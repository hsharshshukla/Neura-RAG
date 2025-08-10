// src/utils/auth.js
export const getToken = () => localStorage.getItem('token') || '';
export const isAuthed = () => !!getToken();
export const logout = () => localStorage.removeItem('token');
