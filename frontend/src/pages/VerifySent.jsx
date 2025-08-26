import React, { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import secureAxios from "../utils/secureAxios";

export default function VerifySent() {
  const { state } = useLocation();
  const navigate = useNavigate();
  const initial = state?.email || "";
  const [email, setEmail] = useState(initial);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const resend = async () => {
    setMsg("");
    setErr("");
    const normalized = (email || "").trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) {
      setErr("Enter a valid email to resend.");
      return;
    }
    setLoading(true);
    try {
      // Backend: POST /api/v1/auth/verify/start -> 204 always
      await secureAxios.post("/auth/verify/start", { email: normalized });
      setMsg("Verification email sent. Check your inbox and spam folder.");
    } catch {
      // Keep it generic to avoid enumeration leaks
      setErr("Could not send verification email. Try again in a minute.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-semibold mb-2 text-center">Verify your email</h1>
        <p className="text-gray-700 text-center">
          We sent a verification link{email ? <> to <strong>{email}</strong></> : ""}. Click the link to activate your account.
        </p>

        {(msg || err) && (
          <div
            className={`mt-4 rounded-lg px-3 py-2 text-sm ${
              err ? "border border-red-200 bg-red-50 text-red-700" : "border border-green-200 bg-green-50 text-green-700"
            }`}
          >
            {err || msg}
          </div>
        )}

        <div className="mt-6 space-y-3">
          <label className="block text-sm text-gray-700">Email to resend</label>
          <input
            type="email"
            value={email}
            onChange={(e)=>setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full p-3 rounded-xl border border-gray-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
            disabled={loading}
          />
          <button
            onClick={resend}
            disabled={loading}
            className={`w-full py-2.5 rounded-xl text-white shadow ${loading ? 'opacity-70 cursor-not-allowed' : 'hover:opacity-95'} bg-gradient-to-r from-teal-500 to-indigo-500`}
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
