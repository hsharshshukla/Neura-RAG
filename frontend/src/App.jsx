// src/App.jsx
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import secureAxios from './utils/secureAxios';

import Chat from './pages/Chat';
import Profile from './pages/Profile';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Layout from './components/Layout';
import Settings from './pages/Settings';
import Home from './pages/Home';
import Pricing from './pages/Pricing';
import About from './pages/About';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import './themeBoot';

import ProtectedRoute from './components/ProtectedRoute';

// Admin
import AdminRoute from './components/AdminRoute';
import AdminLayout from './sections/admin/AdminLayout';
import Overview from './sections/admin/pages/Overview';
import Users from './sections/admin/pages/Users';
import Files from './sections/admin/pages/Files';
import Sessions from './sections/admin/pages/Sessions';
import Billing from './sections/admin/pages/Billing';
import Analytics from './sections/admin/pages/Analytics';
import SettingsAdmin from './sections/admin/pages/Settings';

// Forgot/Reset
import Forgot from './pages/Forgot';
import Reset from './pages/Reset';

// Email verification pages
import VerifySent from './pages/VerifySent';
import VerifyComplete from './pages/VerifyComplete';

// Wrapper: if authed -> /chat, else -> <Home />
function HomeOrChat() {
  const [checked, setChecked] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await secureAxios.get('/auth/me');
        if (!mounted) return;
        setAuthed(Boolean(data?.authenticated));
      } catch {
        if (!mounted) return;
        setAuthed(false);
      } finally {
        if (mounted) setChecked(true);
      }
    })();
    return () => { mounted = false; };
  }, []);

  // Minimal placeholder while probing auth
  if (!checked) return <div className="p-6" />;

  // Only redirect when already authenticated; otherwise show Home
  return authed ? <Navigate to="/chat" replace /> : <Home />;
}

export default function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          {/* Public root that respects auth */}
          <Route path="/" element={<HomeOrChat />} />
          <Route path="/home" element={<HomeOrChat />} />

          {/* Public marketing/legal */}
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/about" element={<About />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* Password flows (public) */}
          <Route path="/forgot" element={<Forgot />} />
          <Route path="/reset" element={<Reset />} />

          {/* Email verification (public) */}
          <Route path="/verify-sent" element={<VerifySent />} />
          <Route path="/verify" element={<VerifyComplete />} />
          <Route path="/verify-email" element={<Navigate to="/verify" replace />} />

          {/* Protected (user) */}
          <Route
            path="/chat/:id"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <Profile />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <Settings />
              </ProtectedRoute>
            }
          />

          {/* Admin (role-guarded) */}
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminLayout />
              </AdminRoute>
            }
          >
            <Route index element={<Overview />} />
            <Route path="users" element={<Users />} />
            <Route path="files" element={<Files />} />
            <Route path="sessions" element={<Sessions />} />
            <Route path="billing" element={<Billing />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="settings" element={<SettingsAdmin />} />
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<div className="p-6">Page not found.</div>} />
        </Routes>
      </Layout>
    </Router>
  );
}
