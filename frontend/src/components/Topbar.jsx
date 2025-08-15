// src/components/TopBar.jsx
import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import SearchCommand from "./SearchCommand";
import { isLoggedIn, isAdmin, logout as authLogout } from "../utils/auth";

const TopBar = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [menuOpen, setMenuOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);

  const menuRef = useRef(null);
  const btnRef = useRef(null);

  // ---- Auth & route state ----
  const authedEmail = localStorage.getItem("email") || "";
  const isAuthed = isLoggedIn();

  const plan = (localStorage.getItem("plan") || "Free").trim();
  const onChatPage = location.pathname.startsWith("/chat");
  const onLogin = location.pathname === "/login";
  const onSignup = location.pathname === "/signup";

  // ---- Keyboard: Ctrl/Cmd+K only on chat page ----
  useEffect(() => {
    const handler = (e) => {
      const mac = navigator.platform.toUpperCase().includes("MAC");
      const hotkey = (mac && e.metaKey) || (!mac && e.ctrlKey);
      if (onChatPage && hotkey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onChatPage]);

  // ---- Close profile menu on outside click / ESC ----
  useEffect(() => {
    const onClickOutside = (e) => {
      if (
        menuOpen &&
        menuRef.current &&
        !menuRef.current.contains(e.target) &&
        btnRef.current &&
        !btnRef.current.contains(e.target)
      ) {
        setMenuOpen(false);
      }
    };
    const onEsc = (e) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEsc);
    };
  }, [menuOpen]);

  const handleLogout = () => {
    authLogout();       // clears token, email, plan, role, legacy keys
    setMenuOpen(false);
    navigate("/");      // ✅ back to Home after logout
  };

  const initials = (() => {
    const name = (localStorage.getItem("name") || authedEmail || "U").trim();
    const parts = name.split(/[@\s._-]+/).filter(Boolean);
    return (parts[0]?.[0] || "U").toUpperCase();
  })();

  const PlanPill = () => {
    const color =
      plan === "Pro"
        ? "bg-emerald-600 text-white"
        : plan === "Mini+"
        ? "bg-indigo-600 text-white"
        : "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100";
    return (
      <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${color}`}>
        {plan}
      </span>
    );
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur">
      <div className="w-full px-3 sm:px-4 lg:px-6">
        {/* 3-column grid: left / center / right */}
        <div className="grid grid-cols-[auto,1fr,auto] items-center h-14 w-full">
          {/* LEFT: Brand */}
          <button
            onClick={() => navigate(isAuthed ? "/chat" : "/")}
            className="justify-self-start flex items-center gap-2"
            aria-label="Go to Home/Chat"
          >
            <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-purple-500 via-fuchsia-500 to-blue-500 shadow-sm" />
            <span className="text-lg font-semibold bg-clip-text text-transparent bg-gradient-to-r from-zinc-900 to-zinc-600 dark:from-zinc-100 dark:to-zinc-300">
              Neura
            </span>
          </button>

          {/* CENTER: Search (chat page only) */}
          {onChatPage ? (
            <div className="justify-self-center w-full max-w-md hidden md:block">
              <div className="relative">
                <input
                  type="text"
                  placeholder="Search — Press Ctrl/⌘ + K"
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-sm placeholder:text-zinc-400 focus:ring-2 focus:ring-purple-500/30"
                  onFocus={() => setCmdOpen(true)}
                  onClick={() => setCmdOpen(true)}
                  readOnly
                />
                <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-zinc-400" />
              </div>
            </div>
          ) : (
            <div /> // keep grid balance
          )}

          {/* RIGHT: Auth-aware + route-aware controls */}
          <div className="justify-self-end flex items-center gap-3">
            {isAuthed ? (
              <>
                {/* ⬇️ Show Admin entry only if role === 'admin' */}
                {isAdmin() && (
                  <button
                    onClick={() => navigate("/admin")}
                    className="px-3 py-2 text-sm rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    Admin
                  </button>
                )}

                <PlanPill />

                <div className="relative">
                  <button
                    ref={btnRef}
                    onClick={() => setMenuOpen((v) => !v)}
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    className="h-11 w-11 rounded-full border-2 border-zinc-300 dark:border-zinc-600 bg-gradient-to-br from-zinc-50 to-white dark:from-zinc-900 dark:to-zinc-900 grid place-items-center text-sm font-semibold"
                    title={authedEmail}
                  >
                    {initials}
                  </button>

                  {menuOpen && (
                    <div
                      ref={menuRef}
                      role="menu"
                      tabIndex={-1}
                      className="absolute right-0 mt-2 w-56 overflow-hidden rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-xl"
                    >
                      <div className="px-4 py-3">
                        <p className="text-sm text-zinc-500">Signed in as</p>
                        <p className="truncate text-sm font-medium">{authedEmail}</p>
                      </div>
                      <div className="h-px bg-zinc-200 dark:bg-zinc-800" />
                      <button
                        onClick={() => {
                          setMenuOpen(false);
                          navigate("/profile");
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      >
                        👤 View Profile
                      </button>
                      <button
                        onClick={() => {
                          setMenuOpen(false);
                          navigate("/settings");
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      >
                        ⚙️ Settings
                      </button>
                      <button
                        onClick={handleLogout}
                        className="w-full text-left px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40"
                      >
                        🚪 Logout
                      </button>
                    </div>
                  )}
                </div>
              </>
            ) : onSignup ? (
              // on /signup show only "Login"
              <button
                onClick={() => navigate("/login")}
                className="px-3 py-2 text-sm rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                Login
              </button>
            ) : onLogin ? (
              // on /login show only "Register"
              <button
                onClick={() => navigate("/signup")}
                className="px-3 py-2 text-sm rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
              >
                Register
              </button>
            ) : (
              // Default public pages (e.g., Home)
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigate("/login")}
                  className="px-3 py-2 text-sm rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                >
                  Login
                </button>
                <button
                  onClick={() => navigate("/signup")}
                  className="px-3 py-2 text-sm rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                >
                  Register
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Mobile search (chat page only) */}
        {onChatPage && (
          <div className="md:hidden pt-2">
            <input
              type="text"
              placeholder="Search — Press Ctrl/⌘ + K"
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-sm placeholder:text-zinc-400 focus:ring-2 focus:ring-purple-500/30"
              onFocus={() => setCmdOpen(true)}
              onClick={() => setCmdOpen(true)}
              readOnly
            />
          </div>
        )}
      </div>

      {/* Command Palette overlay (only opened from chat page) */}
      <SearchCommand open={cmdOpen} onClose={() => setCmdOpen(false)} />
    </header>
  );
};

export default TopBar;



