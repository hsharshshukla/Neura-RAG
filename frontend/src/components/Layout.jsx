// src/components/Layout.jsx
import React from "react";
import { useLocation } from "react-router-dom";
import TopBar from "./TopBar";

const HIDE_TOPBAR_PATHS = new Set([
  "/login",
  "/signup",
  "/forgot",
  "/reset",
  "/verify",
  "/verify-email",
  "/verify-sent",
]);

export default function Layout({ children }) {
  const { pathname } = useLocation();

  // Hide TopBar on auth/verification screens to prevent loops/odd states
  const hideTopBar =
    HIDE_TOPBAR_PATHS.has(pathname) ||
    // also hide when /verify has query (?token=...)
    (pathname === "/verify" || pathname === "/verify-email");

  return (
    <div className="min-h-screen flex flex-col">
      {!hideTopBar && <TopBar />}
      <div className="flex-1">{children}</div>
    </div>
  );
}
