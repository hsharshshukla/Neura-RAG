import React, { useState } from "react";
import secureAxios from "../utils/secureAxios";

export default function Forgot() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await secureAxios.post("/auth/password/forgot", { email });
      setDone(true); // always “success” to avoid user enumeration
    } catch {
      setDone(true);
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="max-w-md mx-auto p-6">
        <h1 className="text-xl font-semibold">Check your email</h1>
        <p className="mt-2 text-gray-600">
          If an account exists for that address, we sent a password reset link.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto p-6">
      <h1 className="text-2xl font-semibold">Reset your password</h1>
      <form className="mt-4 space-y-4" onSubmit={submit}>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full border rounded p-2"
          placeholder="you@example.com"
        />
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-black text-white py-2 disabled:opacity-60"
        >
          {loading ? "Sending…" : "Send reset link"}
        </button>
      </form>
    </div>
  );
}
