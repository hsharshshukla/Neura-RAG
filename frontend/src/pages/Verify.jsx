import React, { useEffect, useState } from "react";
import secureAxios from "../utils/secureAxios";

export default function Verify() {
  const params = new URLSearchParams(window.location.search);
  const initialToken = params.get("token") || "";
  const [token, setToken] = useState(initialToken);
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => setToken(initialToken), [initialToken]);

  const submit = async (e) => {
    e?.preventDefault?.();
    setErr("");
    if (!token) return setErr("Missing token. Please use the link from your email.");
    try {
      await secureAxios.post("/auth/verify/confirm", { token });
      setOk(true);
    } catch (e) {
      setErr("This verification link is invalid or has expired.");
    }
  };

  useEffect(() => { if (token) submit(); }, []); // auto-confirm on page open

  if (ok) {
    return (
      <div className="max-w-md mx-auto p-6">
        <h1 className="text-xl font-semibold">Email verified</h1>
        <p className="mt-2 text-gray-600">
          You can now <a href="/login" className="text-blue-600 underline">log in</a>.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto p-6">
      <h1 className="text-2xl font-semibold">Verify your email</h1>
      <form className="mt-4 space-y-4" onSubmit={submit}>
        <input
          type="text"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="w-full border rounded p-2"
          placeholder="Paste token from email"
          required
        />
        {err && <p className="text-sm text-red-600">{err}</p>}
        <button type="submit" className="w-full rounded bg-black text-white py-2">Verify</button>
      </form>
    </div>
  );
}
