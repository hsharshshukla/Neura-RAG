// src/hooks/useMe.js
import { useEffect, useState } from "react";
import secureAxios from "../utils/secureAxios";

function normalizeRole(raw) {
  const v = String(raw || "").trim().toLowerCase();
  if (!v) return "User";
  // Map common variations to our canonical titles
  const map = {
    owner: "Owner",
    admin: "Admin",
    support: "Support",
    finance: "Finance",
    analyst: "Analyst",
    readonly: "ReadOnly",
    "read-only": "ReadOnly",
    "read_only": "ReadOnly",
    user: "User",
  };
  return map[v] || v.charAt(0).toUpperCase() + v.slice(1);
}

export function useMe() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await secureAxios.get("/auth/me");
        if (!mounted) return;

        const roleRaw = data?.role ?? data?.user?.role ?? "User";
        const normalized = {
          ...data,
          email: data?.email ?? data?.user?.email ?? null,
          role: normalizeRole(roleRaw),
          authenticated: Boolean(data?.authenticated ?? !!data?.user),
          featureFlags: {
            // default allow console until backend wiring is strict
            console_enabled: true,
            ...(data?.featureFlags || {}),
          },
        };

        setMe(normalized);
      } catch {
        if (!mounted) return;
        setMe(null);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  return { me, loading };
}
