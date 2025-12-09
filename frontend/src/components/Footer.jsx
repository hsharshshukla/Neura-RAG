// src/components/Footer.jsx
import { Link } from "react-router-dom";

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="mt-16 border-t border-slate-200 bg-white/80 backdrop-blur-sm">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-6 sm:py-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Brand + tagline */}
        <div className="space-y-1 text-center sm:text-left">
          <div className="text-sm font-semibold tracking-tight text-slate-800">
            Neura
          </div>
          <p className="text-xs sm:text-[13px] text-slate-500">
            © {year} Neura. All rights reserved. Built for ECM / OpenText consultants.
          </p>
        </div>

        {/* Nav links */}
        <nav className="flex flex-wrap items-center justify-center sm:justify-end gap-x-5 gap-y-2 text-xs sm:text-[13px] text-slate-500">
          <Link
            to="/terms"
            className="hover:text-slate-900 hover:underline underline-offset-4 transition-colors"
          >
            Terms &amp; Conditions
          </Link>
          <Link
            to="/privacy"
            className="hover:text-slate-900 hover:underline underline-offset-4 transition-colors"
          >
            Privacy Policy
          </Link>
          <Link
            to="/refund-policy"
            className="hover:text-slate-900 hover:underline underline-offset-4 transition-colors"
          >
            Refund &amp; Cancellation
          </Link>
        </nav>
      </div>
    </footer>
  );
}
