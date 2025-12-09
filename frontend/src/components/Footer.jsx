// src/components/Footer.jsx
import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="border-t mt-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-gray-500">
        <span>© {new Date().getFullYear()} Neura. All rights reserved.</span>

        <nav className="flex flex-wrap items-center gap-4">
          <Link to="/terms" className="hover:text-gray-800">
            Terms & Conditions
          </Link>
          <Link to="/privacy" className="hover:text-gray-800">
            Privacy Policy
          </Link>
          <Link to="/refund-policy" className="hover:text-gray-800">
            Refund & Cancellation
          </Link>
        </nav>
      </div>
    </footer>
  );
}
