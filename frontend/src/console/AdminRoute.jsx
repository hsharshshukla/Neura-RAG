// src/console/AdminRoute.jsx
import { Navigate } from "react-router-dom";
import { useMe } from "../hooks/useMe";

function toLowerSet(list = []) {
  return new Set(list.map((x) => String(x || "").trim().toLowerCase()));
}

/**
 * roles: array of allowed roles (case-insensitive), e.g.
 * ["Owner","Admin","Support","Finance","Analyst","ReadOnly"]
 * flag: optional feature flag string; defaults to "console_enabled"
 *
 * Note: If user is authenticated but not authorized, we render
 * a small "Access denied" message instead of redirecting to "/",
 * so we don't bounce them back to /chat.
 */
export default function AdminRoute({ children, roles, flag = "console_enabled" }) {
  const { me, loading } = useMe();

  if (loading) return null;

  // Not logged in → go to login
  if (!me || !me.authenticated) {
    return <Navigate to="/login" replace />;
  }

  // Feature-flag gate
  if (me.featureFlags && me.featureFlags[flag] === false) {
    return (
      <div className="p-6">
        <div className="text-sm text-red-600">Access denied (console disabled).</div>
      </div>
    );
  }

  // Role gate (case-insensitive)
  if (roles && roles.length) {
    const allowed = toLowerSet(roles);
    const myRole = String(me.role || "User").trim().toLowerCase();
    if (!allowed.has(myRole)) {
      return (
        <div className="p-6">
          <div className="text-sm text-red-600">Access denied for role: {me.role}</div>
        </div>
      );
    }
  }

  return children;
}
