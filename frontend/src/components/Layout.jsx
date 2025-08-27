// src/components/Layout.jsx
import React from "react";
import { useLocation } from "react-router-dom";
import TopBar from "./TopBar";

// Only hide on email verification screens (optional).
// Show TopBar on login/signup/forgot/reset so users always see brand + nav.
const HIDE_TOPBAR_PATHS = new Set([
  "/verify",
  "/verify-email",
  "/verify-sent",
]);

export default function Layout({ children }) {
  const { pathname } = useLocation();
  const hideTopBar =
    HIDE_TOPBAR_PATHS.has(pathname) ||
    (pathname === "/verify" || pathname === "/verify-email"); // handles query e.g. ?token=...

  return (
    <div className="min-h-screen flex flex-col">
      {!hideTopBar && <TopBar />}
      <div className="flex-1">{children}</div>
    </div>
  );
}
