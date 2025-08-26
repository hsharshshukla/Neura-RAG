// src/pages/VerifySent.jsx
import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import secureAxios from "../utils/secureAxios";

export default function VerifySent() {
  const { state } = useLocation();
  const navigate = useNavigate();

  // Prefill from navigation state or query param
  const urlEmail = new URLSearchParams(window.location.search).get("email") || "";
  const email = (state?.email || urlEmail || "").trim().toLowerCase();

  const [msg, setMsg] = React.useState("");
  const [err, setErr] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  const resend = async () => {
    setMsg("");
    setErr("");
    if (!email) {
      setErr("No email available to resend. Please sign up again.");
      return;
    }
    setLoading(true);
    try {
      // Backend: POST /api/v1/auth/verify/start -> 204 (no enumeration)
      await secureAxios.post("/auth/verify/start", { email });
      setMsg("Verification email sent. Please check your inbox and spam folder.");
    } catch {
      setErr("Could not send verification email. Try again in a minute.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-semibold mb-2 text-center">Verify your email</h1>
        <p className="text-gray-700 text-center mb-4">
          We sent a verification link to your email. Click the link to activate your account.
        </p>

        <label className="block text-sm text-gray-700 mb-1">Email</label>
        {/* Display-only (not editable) */}
        <input
          type="email"
          value={email}
          disabled
          aria-readonly="true"
          className="w-full p-3 rounded-xl border border-gray-200 bg-gray-100 text-gray-800 cursor-not-allowed"
        />
        {/* Hidden copy-safe value (if needed in future) */}
        <input type="hidden" value={email} readOnly />

        {!email && (
          <div className="mt-2 text-xs text-red-700">
            We couldn’t detect your email from the signup flow. Please sign up again.
          </div>
        )}

        {(msg || err) && (
          <div
            className={`mt-4 rounded-lg px-3 py-2 text-sm ${
              err
                ? "border border-red-200 bg-red-50 text-red-700"
                : "border border-green-200 bg-green-50 text-green-700"
            }`}
          >
            {err || msg}
          </div>
        )}

        <div className="mt-6 space-y-3">
          <button
            onClick={resend}
            disabled={loading || !email}
            className={`w-full py-2.5 rounded-xl text-white shadow ${
              loading || !email ? "opacity-70 cursor-not-allowed" : "hover:opacity-95"
            } bg-gradient-to-r from-teal-500 to-indigo-500`}
          >
            {loading ? "Sending…" : "Resend verification email"}
          </button>
          <button
            onClick={() => navigate("/login")}
            className="w-full text-teal-700 hover:underline text-sm"
          >
            Back to login
          </button>
        </div>
      </div>
    </div>
  );
}
