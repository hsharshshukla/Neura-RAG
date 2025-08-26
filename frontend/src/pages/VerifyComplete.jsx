import React, { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import secureAxios from "../utils/secureAxios";

export default function VerifyComplete() {
  const [status, setStatus] = useState("Verifying…");
  const [ok, setOk] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      const token = searchParams.get("token");
      if (!token) {
        setStatus("Invalid verification link.");
        setOk(false);
        return;
      }
      try {
        // Backend: POST /api/v1/auth/verify/confirm { token }
        await secureAxios.post("/auth/verify/confirm", { token });
        setOk(true);
        setStatus("Email verified! You can log in now.");
      } catch (e) {
        const msg = e?.response?.data?.detail || "Verification failed. The link may be expired or already used.";
        setStatus(msg);
        setOk(false);
      }
    })();
  }, [searchParams]);

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 shadow-sm text-center">
        <h1 className="text-2xl font-semibold mb-4">Email Verification</h1>
        <p className="mb-6">{status}</p>
        <button
          onClick={() => navigate("/login")}
          className={`w-full py-2.5 rounded-xl text-white shadow ${
            ok ? 'bg-green-600 hover:bg-green-700' : 'bg-gray-800 hover:bg-black'
          }`}
        >
          Go to Login
        </button>
      </div>
    </div>
  );
}
