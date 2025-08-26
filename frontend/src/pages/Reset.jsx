import React, { useState, useEffect } from "react";
import secureAxios from "../utils/secureAxios";

export default function Reset() {
  const params = new URLSearchParams(window.location.search);
  const initialToken = params.get("token") || "";
  const [token, setToken] = useState(initialToken);
  const [pw1, setPw1] = useState("");
  const [pw2, setPw2] = useState("");
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => setToken(initialToken), [initialToken]);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (pw1.length < 8) return setErr("Password must be at least 8 characters.");
    if (pw1 !== pw2) return setErr("Passwords do not match.");
    try {
      await secureAxios.post("/auth/password/reset", { token, new_password: pw1 });
      setOk(true);
    } catch {
      setErr("The reset link is invalid or has expired.");
    }
  };

  if (ok) {
    return (
      <div className="max-w-md mx-auto p-6">
        <h1 className="text-xl font-semibold">Password updated</h1>
        <p className="mt-2 text-gray-600">
          You can now <a href="/login" className="text-blue-600 underline">log in</a> with your new password.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto p-6">
      <h1 className="text-2xl font-semibold">Choose a new password</h1>
      <form className="mt-4 space-y-4" onSubmit={submit}>
        <input
          type="password"
          value={pw1}
          onChange={(e) => setPw1(e.target.value)}
          placeholder="New password"
          className="w-full border rounded p-2"
          required
        />
        <input
          type="password"
          value={pw2}
          onChange={(e) => setPw2(e.target.value)}
          placeholder="Confirm new password"
          className="w-full border rounded p-2"
          required
        />
        {err && <p className="text-sm text-red-600">{err}</p>}
        <button type="submit" className="w-full rounded bg-black text-white py-2">Update password</button>
      </form>
    </div>
  );
}
