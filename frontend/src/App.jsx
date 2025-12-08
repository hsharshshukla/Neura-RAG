// src/App.jsx
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import secureAxios from "./utils/secureAxios";

import Chat from "./pages/Chat";
import Profile from "./pages/Profile";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Layout from "./components/Layout";
import Settings from "./pages/Settings";
import Home from "./pages/Home";
import Pricing from "./pages/Pricing";
import About from "./pages/About";
import Privacy from "./pages/Privacy";
import Terms from "./pages/Terms";
import Coupons from "./sections/admin/pages/Coupons";
import "./themeBoot";

import ProtectedRoute from "./components/ProtectedRoute";

// Legacy Admin
import AdminRoute from "./components/AdminRoute";
import AdminLayout from "./sections/admin/AdminLayout";
import Overview from "./sections/admin/pages/Overview";
import Users from "./sections/admin/pages/Users";
import Files from "./sections/admin/pages/Files";
import Sessions from "./sections/admin/pages/Sessions";
import Billing from "./sections/admin/pages/Billing";
import Analytics from "./sections/admin/pages/Analytics";
import SettingsAdmin from "./sections/admin/pages/Settings";
import RefundPolicy from "./pages/RefundPolicy";

// NEW Console (feature-flag + role-guarded)
import ConsoleRoute from "./console/AdminRoute";
import ConsoleLayout from "./console/AdminLayout";
import ConsoleOverview from "./console/pages/Overview";
import ConsoleUsers from "./console/pages/Users";
import ConsoleCoupons from "./console/pages/Coupons";
import ConsoleFiles from "./console/pages/Files";
import ConsoleSessions from "./console/pages/Sessions";
import ConsoleBilling from "./console/pages/Billing";
import ConsoleSessionView from "./console/pages/SessionView";
import ConsoleChatAnalytics from "./console/pages/ChatAnalytics";
import ConsoleBulkUpload from "./console/pages/BulkUpload";
// Forgot/Reset
import Forgot from "./pages/Forgot";
import Reset from "./pages/Reset";

// Email verification pages
import VerifySent from "./pages/VerifySent";
import VerifyComplete from "./pages/VerifyComplete";

// ✅ Billing success
import BillingSuccess from "./pages/BillingSuccess";

// Wrapper: if authed -> /chat, else -> <Home />
function HomeOrChat() {
  const [checked, setChecked] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await secureAxios.get("/auth/me");
        if (!mounted) return;
        setAuthed(Boolean(data?.authenticated));
      } catch {
        if (!mounted) return;
        setAuthed(false);
      } finally {
        if (mounted) setChecked(true);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  if (!checked) return <div className="p-6" />;
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
          <Route path="/refund-policy" element={<RefundPolicy />} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* Password flows */}
          <Route path="/forgot" element={<Forgot />} />
          <Route path="/reset" element={<Reset />} />

          {/* Email verification */}
          <Route path="/verify-sent" element={<VerifySent />} />
          <Route path="/verify" element={<VerifyComplete />} />
          <Route path="/verify-email" element={<Navigate to="/verify" replace />} />

          {/* ✅ Billing success page */}
          <Route path="/billing/success" element={<BillingSuccess />} />

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

          {/* Legacy Admin (role-guarded) */}
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
            <Route path="coupons" element={<Coupons />} />
          </Route>

          {/* NEW Console (admin dashboard) */}
          <Route
            path="/console"
            element={
              <ConsoleRoute roles={["Owner", "Admin", "Support", "Finance", "Analyst", "ReadOnly"]}>
                <ConsoleLayout />
              </ConsoleRoute>
            }
          >
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<ConsoleOverview />} />
            <Route path="users" element={<ConsoleUsers />} />
            <Route path="files" element={<ConsoleFiles />} />
            <Route path="sessions" element={<ConsoleSessions />} />
            <Route path="coupons" element={<ConsoleCoupons />} />
            <Route path="billing" element={<ConsoleBilling />} />
            <Route path="sessions/:id" element={<ConsoleSessionView />} />
            <Route path="chat-analytics" element={<ConsoleChatAnalytics />} />
            <Route path="bulk-upload" element={<ConsoleBulkUpload />} />
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<div className="p-6">Page not found.</div>} />
        </Routes>
      </Layout>
    </Router>
  );
}
