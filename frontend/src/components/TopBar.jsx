// src/components/TopBar.jsx
import React, { useEffect, useRef, useState, Suspense } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { isLoggedIn, isAdmin, logout as authLogout } from "../utils/auth";
import secureAxios from "../utils/secureAxios";

// Lazy-load SearchCommand so TopBar can't crash on pages that don't need it
const SearchCommand = React.lazy(() => import("./SearchCommand"));

function normalizePath(pathname) {
  if (!pathname) return "/";
  const p = pathname.toLowerCase();
  return p.endsWith("/") && p !== "/" ? p.slice(0, -1) : p;
}

const TopBar = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [menuOpen, setMenuOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [authed, setAuthed] = useState(isLoggedIn()); // seed from local
  const [tier, setTier] = useState((localStorage.getItem("tier") || "free").toLowerCase());
  const [loadingTier, setLoadingTier] = useState(true);

  const menuRef = useRef(null);
  const btnRef = useRef(null);

  // Soft probe once to sync cookie-backed session with local flags
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await secureAxios.get("/auth/me"); // never 401
        if (!mounted) return;
        if (!data?.authenticated) {
          authLogout();
          setAuthed(false);
        } else {
          setAuthed(true);
        }
      } catch {
        // ignore transient errors; keep current flag
      }
    })();

    const onAuthChanged = () => setAuthed(isLoggedIn());
    window.addEventListener("auth-changed", onAuthChanged);
    return () => {
      mounted = false;
      window.removeEventListener("auth-changed", onAuthChanged);
    };
  }, []);

  // Re-evaluate on route changes (after a login redirect, etc.)
  useEffect(() => {
    setAuthed(isLoggedIn());
  }, [location.pathname]);

  // Fetch tier (billing/status → fallback user/profile), keep localStorage in sync
  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!authed) {
        setTier("free");
        setLoadingTier(false);
        return;
      }
      setLoadingTier(true);
      try {
        const { data } = await secureAxios.get("/billing/status");
        const t = String(data?.tier || "free").toLowerCase();
        if (!mounted) return;
        setTier(t);
        localStorage.setItem("tier", t);
      } catch {
        try {
          const { data } = await secureAxios.get("/user/profile");
          const t = String(data?.tier || "free").toLowerCase();
          if (!mounted) return;
          setTier(t);
          localStorage.setItem("tier", t);
        } catch {
          if (!mounted) return;
          setTier("free");
        }
      } finally {
        if (mounted) setLoadingTier(false);
      }
    })();
    return () => { mounted = false; };
  }, [authed]);

  // Current route flags (normalized, resilient to trailing slashes/case)
  const path = normalizePath(location.pathname);
  const onChat = path.startsWith("/chat");
  const onLogin = path === "/login";
  const onSignup = path === "/signup";

  // Hotkey: Ctrl/Cmd+K opens command palette on chat page
  useEffect(() => {
    const handler = (e) => {
      const mac = navigator.platform.toUpperCase().includes("MAC");
      const hotkey = (mac && e.metaKey) || (!mac && e.ctrlKey);
      if (onChat && hotkey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onChat]);

  // Close profile menu on outside click / ESC
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

  const handleLogout = async () => {
    try { await secureAxios.post("/auth/logout"); } catch {}
    authLogout();
    setMenuOpen(false);
    setAuthed(false);
    setTier("free");
    navigate("/"); // home after logout
  };

  // UI bits
  const authedEmail = localStorage.getItem("email") || "";
  const planLabel =
    tier === "pro" ? "Pro" :
    tier === "mini" || tier === "mini+" ? "Mini+" : "Free";

  const initials = (() => {
    const name = (localStorage.getItem("name") || authedEmail || "U").trim();
    const parts = name.split(/[@\s._-]+/).filter(Boolean);
    return (parts[0]?.[0] || "U").toUpperCase();
  })();

  const PlanPill = () => {
    const color =
      planLabel === "Pro"
        ? "bg-emerald-600 text-white"
        : planLabel === "Mini+"
        ? "bg-indigo-600 text-white"
        : "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100";
    return (
      <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${color}`} title={`Current plan: ${planLabel}`}>
        {loadingTier ? "…" : planLabel}
      </span>
    );
  };

  const onUpgradeClick = () => {
    if (location.pathname !== "/pricing") navigate("/pricing");
  };
  const onManageClick = () => {
    // Later: open billing portal/manage URL when available
    navigate("/pricing");
  };

  // Helper: treat mini/mini+ as Mini+
  const isMiniTier = tier === "mini" || tier === "mini+";

  return (
    <header className="sticky top-0 z-40 w-full border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur">
      <div className="w-full px-3 sm:px-4 lg:px-6">
        {/* 3-column grid: left / center / right */}
        <div className="grid grid-cols-[auto,1fr,auto] items-center h-14 w-full">
          {/* LEFT: Brand → Home if logged out, Chat if logged in */}
          <button
            onClick={() => navigate(authed ? "/chat" : "/")}
            className="justify-self-start flex items-center gap-2"
            aria-label="Go to Home or Chat"
          >
            {/* Brand mark */}
            <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-purple-500 via-fuchsia-500 to-blue-500 shadow-sm" />
            {/* Wordmark */}
            <span className="text-lg font-semibold bg-clip-text text-transparent bg-gradient-to-r from-zinc-900 to-zinc-600 dark:from-zinc-100 dark:to-zinc-300">
              Neura
            </span>
          </button>

          {/* CENTER: Command/Search (only on chat) */}
          {onChat ? (
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
            <div />
          )}

          {/* RIGHT: Auth-aware controls */}
          <div className="justify-self-end flex items-center gap-3">
            {authed ? (
              <>
                {isAdmin() && (
                  <Link
                    to="/admin"
                    className="px-3 py-2 text-sm rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    Admin
                  </Link>
                )}

                {/* Plan badge */}
                <PlanPill />

                {/* Upgrade / Manage */}
                {(isMiniTier || tier === "pro") ? (
                  <>
                    {/* Desktop Manage */}
                    <button
                      onClick={onManageClick}
                      className="hidden sm:inline-flex items-center rounded-xl bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-black"
                      title="Manage billing and plan"
                    >
                      Manage plan
                    </button>
                    {/* Mobile Manage */}
                    <button
                      onClick={onManageClick}
                      className="sm:hidden inline-flex items-center rounded-lg border px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                      aria-label="Manage plan"
                    >
                      Manage
                    </button>
                  </>
                ) : (
                  <>
                    {/* Desktop Upgrade */}
                    <button
                      onClick={onUpgradeClick}
                      className="hidden sm:inline-flex items-center rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                      title="Upgrade"
                    >
                      Upgrade
                    </button>
                    {/* Mobile Upgrade */}
                    <button
                      onClick={onUpgradeClick}
                      className="sm:hidden inline-flex items-center rounded-lg border px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                      aria-label="Upgrade"
                    >
                      Upgrade
                    </button>
                  </>
                )}

                {/* Avatar / menu */}
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
                        onClick={() => { setMenuOpen(false); navigate("/profile"); }}
                        className="w-full text-left px-4 py-2.5 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      >
                        👤 View Profile
                      </button>
                      <button
                        onClick={() => { setMenuOpen(false); navigate("/settings"); }}
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
            ) : (
              <>
                {/* Logged OUT */}
                {onLogin ? (
                  <button
                    onClick={() => navigate("/signup")}
                    className="px-3 py-2 text-sm rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  >
                    Register
                  </button>
                ) : onSignup ? (
                  <button
                    onClick={() => navigate("/login")}
                    className="px-3 py-2 text-sm rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    Login
                  </button>
                ) : (
                  // Home (and other public pages): show both
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
              </>
            )}
          </div>
        </div>

        {/* Mobile search (chat page only) */}
        {onChat && (
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

      {/* Command Palette overlay (lazy, only loaded when needed) */}
      {onChat && (
        <Suspense fallback={null}>
          <SearchCommand open={cmdOpen} onClose={() => setCmdOpen(false)} />
        </Suspense>
      )}
    </header>
  );
};

export default TopBar;
