// src/pages/BillingSuccess.jsx
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import secureAxios from "../utils/secureAxios";

function useQuery() {
  const { search } = useLocation();
  return useMemo(() => new URLSearchParams(search), [search]);
}

export default function BillingSuccess() {
  const q = useQuery();
  const navigate = useNavigate();

  // Extract info passed by dummy provider
  const plan = (q.get("plan") || "").toLowerCase(); // mini | pro
  const user = q.get("user") || "";                 // user id (dummy provider)
  const currency = q.get("currency") || "";         // INR | USD
  const amount = q.get("amount") || "";             // minor units

  const [phase, setPhase] = useState("processing"); // processing | done | error
  const [msg, setMsg] = useState("Validating payment…");

  const targetTier = useMemo(
    () => (plan === "mini" || plan === "pro") ? plan : null,
    [plan]
  );

  // Pretty total from minor units (₹149 / $5.00)
  const prettyAmount = useMemo(() => {
    const n = Number(amount);
    if (!Number.isFinite(n) || n <= 0) return "";
    if (currency === "INR") return `₹${Math.round(n / 100)}`;
    const s = (n / 100);
    return s % 1 === 0 ? `$${s.toFixed(0)}` : `$${s.toFixed(2)}`;
  }, [amount, currency]);

  useEffect(() => {
    let mounted = true;
    let timer;

    const tryWebhook = async () => {
      // In PAYMENT_GATEWAY=dummy, the BE will accept this and upgrade immediately.
      if (!targetTier || !user) return false;
      try {
        await secureAxios.post(
          "/billing/webhook",
          {
            event: "dummy",
            user_id: Number(user),
            plan: targetTier,
            payment_id: `dummy_${Date.now()}`,
            status: "paid",
            currency,
            amount_minor: Number(amount) || undefined,
          },
          { headers: { "Content-Type": "application/json" } }
        );
        return true;
      } catch {
        return false;
      }
    };

    const devBypass = async () => {
      // Authenticated, safe dev-only activator if webhook path failed.
      try {
        await secureAxios.post(
          "/billing/dev/activate",
          { plan: targetTier },
          { headers: { "Content-Type": "application/json" } }
        );
        return true;
      } catch {
        return false;
      }
    };

    const pollStatus = async (attempt = 0) => {
      try {
        const { data } = await secureAxios.get("/billing/status");
        const currentTier = String(data?.tier || "free").toLowerCase();

        if (!mounted) return;

        if (targetTier && currentTier === targetTier) {
          localStorage.setItem("tier", currentTier);
          setPhase("done");
          setMsg(
            `You're on ${currentTier === "pro" ? "Pro" : "Mini+"} now. ${
              prettyAmount ? `${prettyAmount} charged today.` : ""
            } Your subscription starts today.`
          );
          return;
        }

        if (attempt >= 10) {
          setPhase("error");
          setMsg("We couldn’t confirm your subscription yet. Please refresh or contact support.");
          return;
        }

        timer = setTimeout(() => pollStatus(attempt + 1), 1500);
      } catch {
        if (!mounted) return;
        if (attempt >= 10) {
          setPhase("error");
          setMsg("We couldn’t confirm your subscription yet. Please refresh or contact support.");
        } else {
          timer = setTimeout(() => pollStatus(attempt + 1), 1500);
        }
      }
    };

    (async () => {
      const okWebhook = await tryWebhook();
      if (!okWebhook) {
        // Fall back to dev bypass (works only when PAYMENT_GATEWAY=dummy)
        await devBypass();
      }
      await pollStatus(0);
    })();

    return () => {
      mounted = false;
      if (timer) clearTimeout(timer);
    };
  }, [targetTier, user, amount, currency, prettyAmount]);

  const Heading = () => (
    <h1
      className={`text-2xl font-semibold ${
        phase === "done" ? "text-emerald-600" : phase === "error" ? "text-red-600" : ""
      }`}
    >
      {phase === "processing" && "Finishing up…"}
      {phase === "done" && "All set! 🎉"}
      {phase === "error" && "Payment confirmation issue"}
    </h1>
  );

  return (
    <section className="py-16">
      <div className="mx-auto max-w-xl px-4 text-center">
        <Heading />
        <p className="mt-4 text-gray-700">{msg}</p>

        {/* Clean summary — human amounts, no “minor units” */}
        {(targetTier || prettyAmount) && (
          <p className="mt-2 text-sm text-gray-600">
            {prettyAmount ? `Charged ${prettyAmount}${currency ? ` ${currency}` : ""}. ` : ""}
            Your subscription starts today.
          </p>
        )}

        <div className="mt-8 flex items-center justify-center gap-3">
          <button
            onClick={() => navigate("/chat")}
            className="rounded-lg bg-gray-900 text-white px-4 py-2 text-sm hover:bg-black"
          >
            Go to Chat
          </button>
          <Link
            to="/pricing"
            className="rounded-lg border px-4 py-2 text-sm hover:bg-gray-50"
          >
            Manage plan
          </Link>
        </div>

        <div className="mt-6 text-xs text-gray-500">
          If this page doesn’t update automatically, refresh or revisit{" "}
          <Link to="/pricing" className="underline">Pricing</Link>.
        </div>
      </div>
    </section>
  );
}
