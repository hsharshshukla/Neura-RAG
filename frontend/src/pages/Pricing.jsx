import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import secureAxios from "../utils/secureAxios";
import { motion } from "framer-motion";
import { Check, Sparkles, Stars, Shield, Cpu, Globe, GaugeCircle } from "lucide-react";

// ------------------------------
// Region + currency detection (client fallback)
// ------------------------------
const DETECT_IS_INDIA = () => {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    if (tz.toLowerCase().includes("kolkata")) return true;
    const loc = navigator.language || "";
    if (/-IN$/i.test(loc)) return true;
  } catch {}
  return false;
};

// ------------------------------
// Constants
// ------------------------------
const TOKEN_CAP = { free: 200_000, mini: 500_000, pro: 1_000_000 };
const MODEL_BY_TIER = { free: "gpt-3.5-turbo", mini: "gpt-4o-mini", pro: "gpt-4o" };

// localStorage helpers to persist "cancellation scheduled" across refresh
const LS_KEYS = {
  plan: "cancel_scheduled_plan",           // "free"
  next: "cancel_next_renewal_iso",         // ISO string
  tierAtSchedule: "cancel_scheduled_tier", // "mini" | "pro"
};

const readLsCancel = () => {
  try {
    const plan = localStorage.getItem(LS_KEYS.plan);
    const next = localStorage.getItem(LS_KEYS.next);
    const tierAtSchedule = localStorage.getItem(LS_KEYS.tierAtSchedule);
    return { plan, next, tierAtSchedule };
  } catch {
    return { plan: null, next: null, tierAtSchedule: null };
  }
};

const writeLsCancel = (plan, next, tier) => {
  try {
    if (plan) localStorage.setItem(LS_KEYS.plan, plan);
    if (next) localStorage.setItem(LS_KEYS.next, next);
    if (tier) localStorage.setItem(LS_KEYS.tierAtSchedule, tier);
  } catch {}
};

const clearLsCancel = () => {
  try {
    localStorage.removeItem(LS_KEYS.plan);
    localStorage.removeItem(LS_KEYS.next);
    localStorage.removeItem(LS_KEYS.tierAtSchedule);
  } catch {}
};

// Format "expires on" date consistently (e.g., 14 Sep 2025)
const formatExpiry = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

// Pretty number
const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString() : n);

// Small utility badge
const TinyBadge = ({ children, className = "" }) => (
  <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{children}</span>
);

// Feature row
const Feature = ({ children }) => (
  <li className="flex items-center gap-2 text-sm text-gray-700"><Check className="h-4 w-4" />{children}</li>
);

export default function Pricing() {
  const navigate = useNavigate();

  // --- Auth & plan state ---
  const [authed, setAuthed] = useState(false);
  const [tier, setTier] = useState(null); // 'free' | 'mini' | 'pro' | null
  const [manageUrl, setManageUrl] = useState(null);

  // Cancellation scheduling info
  const [scheduledPlan, setScheduledPlan] = useState(null); // e.g. 'free'
  const [nextRenewal, setNextRenewal] = useState(null);     // ISO string

  // Local banner after cancel
  const [cancelJustScheduled, setCancelJustScheduled] = useState(false);

  // --- Canonical prices/currency/region from server ---
  const [serverCurrency, setServerCurrency] = useState(null); // 'INR' | 'USD'
  const [serverCountry, setServerCountry] = useState(null);   // e.g. 'IN'
  const [serverPrices, setServerPrices] = useState({
    mini_minor: 14900,
    pro_minor: 50000,
    mini_display: "₹149/mo",
    pro_display: "₹500/mo",
  });

  // --- VPN guard (optional). Fail-open if not present. ---
  const [vpnInfo, setVpnInfo] = useState({ vpn: false, block: false, reason: "ok", country: null, currency: null });

  // Heuristic fallback only if server didn't tell us currency yet
  const initialIsIndia = useMemo(() => DETECT_IS_INDIA(), []);
  const fallbackCurrency = initialIsIndia ? "INR" : "USD";

  // Utility: has the stored nextRenewal passed?
  const isPast = (iso) => {
    if (!iso) return false;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return false;
    return d.getTime() < Date.now();
  };

  // =========================
  // 1) Probe auth + billing status
  // =========================
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const me = await secureAxios.get("/auth/me"); // non-401
        const isAuthed = Boolean(me?.data?.authenticated);
        if (!mounted) return;
        setAuthed(isAuthed);

        if (isAuthed) {
          const s = await secureAxios.get("/billing/status");
          const t = String(s?.data?.tier || "free").toLowerCase();
          setTier(t);
          setManageUrl(s?.data?.manage_url || null);

          // Server truth (preferred)
          let serverScheduledPlan = s?.data?.scheduled_plan ? String(s.data.scheduled_plan).toLowerCase() : null;
          let serverNextRenewal = s?.data?.next_renewal || null;

          // If server didn't return flags (MVP/older DB), use LS fallback
          if (!serverScheduledPlan || !serverNextRenewal) {
            const { plan: lsPlan, next: lsNext, tierAtSchedule } = readLsCancel();
            const lsLooksValid =
              lsPlan === "free" && (t === (tierAtSchedule || t)) && !!lsNext && !isPast(lsNext) && (t === "mini" || t === "pro");
            if (lsLooksValid) {
              serverScheduledPlan = "free";
              serverNextRenewal = lsNext;
            } else {
              clearLsCancel();
            }
          }

          if (serverScheduledPlan) setScheduledPlan(serverScheduledPlan);
          if (serverNextRenewal) setNextRenewal(serverNextRenewal);

          if (!(t === "mini" || t === "pro") || !serverScheduledPlan) {
            clearLsCancel();
          }

          localStorage.setItem("tier", t);
        } else {
          setTier(null); setManageUrl(null); setScheduledPlan(null); setNextRenewal(null); localStorage.removeItem("tier"); clearLsCancel();
        }
      } catch {
        if (!mounted) return;
        setAuthed(false); setTier(null); setManageUrl(null); setScheduledPlan(null); setNextRenewal(null); clearLsCancel();
      }
    })();
    return () => { mounted = false; };
  }, []);

  // =========================
  // 2) Server prices/currency (canonical)
  // =========================
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await secureAxios.get("/billing/prices");
        if (!mounted) return;
        if (data?.currency) setServerCurrency(data.currency);
        if (data?.country) setServerCountry(data.country);
        setServerPrices({
          mini_minor: data?.mini_minor ?? 14900,
          pro_minor: data?.pro_minor ?? 50000,
          mini_display: data?.mini_display ?? "₹149/mo",
          pro_display: data?.pro_display ?? "₹500/mo",
        });
      } catch {}
    })();
    return () => { mounted = false; };
  }, []);

  // =========================
  // 3) VPN guard (optional)
  // =========================
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await secureAxios.get("/billing/guard");
        if (!mounted) return;
        setVpnInfo({
          vpn: Boolean(data?.vpn),
          block: Boolean(data?.block),
          reason: data?.reason || "ok",
          country: data?.country || serverCountry,
          currency: data?.currency || serverCurrency,
        });
      } catch {}
    })();
    return () => { mounted = false; };
  }, [serverCountry, serverCurrency]);

  // =========================
  // Currency to display (no user toggle; server or fallback)
  // =========================
  const displayCurrency = serverCurrency || vpnInfo?.currency || fallbackCurrency;
  const priceFree = "Free"; // never show $0/₹0
  const priceMini = serverPrices.mini_display;
  const pricePro = serverPrices.pro_display;

  // =========================
  // Plan cards (content)
  // =========================
  const plans = [
    {
      id: "free",
      name: "Free",
      blurb: "Try core features with fair-use limits.",
      price: priceFree,
      model: MODEL_BY_TIER.free,
      tokens: TOKEN_CAP.free,
      icon: Shield,
      features: [
        "20 chats/day",
        "Session-only search",
        "Basic OCR",
        "Uploads: 5 docs/session",
        "Reference by document name",
      ],
    },
    {
      id: "mini",
      name: "Mini+",
      blurb: "Best for individuals. Faster responses.",
      price: priceMini,
      model: MODEL_BY_TIER.mini,
      tokens: TOKEN_CAP.mini,
      icon: GaugeCircle,
      features: [
        "Unlimited chats (fair use)",
        "Session-only search",
        "Faster responses (priority queue)",
        "Uploads: 20 docs/session",
        "Basic analytics per chat",
      ],
      primary: true,
      badge: "Most Popular",
    },
    {
      id: "pro",
      name: "Pro",
      blurb: "Teams & power users. Global search + exports.",
      price: pricePro,
      model: MODEL_BY_TIER.pro,
      tokens: TOKEN_CAP.pro,
      icon: Cpu,
      features: [
        "Unlimited chats (fair use)",
        "Global document search (Pro pool)",
        "Priority queue (fastest)",
        "Unlimited uploads + Exports (PDF/JSON/MD)",
        "Usage analytics dashboard",
      ],
    },
    {
      id: "enterprise",
      name: "Enterprise",
      blurb: "Scale securely with SSO, SLAs and support.",
      price: "Custom",
      model: "Custom",
      tokens: "Custom",
      icon: Globe,
      features: [
        "Multi-seat & Admin controls",
        "Bulk ingestion & API",
        "SSO & SLA",
        "Dedicated support",
      ],
      enterprise: true,
    },
  ];

  // =========================
  // CTA logic (per rules)
  // =========================
  const isCurrent = (id) => authed && tier && id === tier;
  const cancellationScheduled = authed && String(scheduledPlan || "").toLowerCase() === "free";

  const isActionableUpgrade = (planId) => {
    if (!authed) return false;
    if (vpnInfo?.block) return false;
    if (planId === "enterprise") return false;
    if (tier === "free" && (planId === "mini" || planId === "pro")) return true;
    if (tier === "mini" && planId === "pro") return true;
    return false;
  };

  const ctaLabel = (plan, loadingPlan) => {
    if (!authed) return "Login to upgrade";
    if (plan.enterprise) return "Contact sales";
    if (isCurrent(plan.id)) {
      if (cancellationScheduled) return "Cancellation scheduled";
      if (tier === "mini" || tier === "pro") return "Cancel plan";
      return "Current plan";
    }
    if (isActionableUpgrade(plan.id)) return loadingPlan === plan.id ? "Redirecting…" : "Upgrade";
    if (tier === "pro" && plan.id === "mini") return "Downgrade at renewal";
    if (tier === "mini" && plan.id === "free") return "Downgrade at renewal";
    if (tier === "pro" && plan.id === "free") return "Cancel at renewal";
    return "Get started";
  };

  // =========================
  // Actions
  // =========================
  const [loadingPlan, setLoadingPlan] = useState(null);

  const startCheckout = async (planId) => {
    try {
      if (!authed) { navigate("/login"); return; }
      if (vpnInfo?.block) { alert("Billing is disabled while VPN/proxy is detected. Please disable VPN and retry."); return; }
      if (!isActionableUpgrade(planId)) return;

      setLoadingPlan(planId);
      const { data } = await secureAxios.post("/billing/checkout", { plan: planId });
      if (data?.url) { window.location.href = data.url; }
      else { alert("Could not start checkout. Please try again."); }
    } catch (e) {
      console.error(e);
      const msg = typeof e?.response?.data?.detail === "object"
        ? JSON.stringify(e.response.data.detail)
        : e?.response?.data?.detail || "Checkout failed. Please try again.";
      alert(msg);
    } finally {
      setLoadingPlan(null);
    }
  };

  const cancelPlan = async () => {
    try {
      const { data } = await secureAxios.post("/billing/cancel", { mode: "period_end" });
      const sched = data?.scheduled_plan ? String(data.scheduled_plan).toLowerCase() : "free";
      const next = data?.next_renewal || null;
      setScheduledPlan(sched);
      if (next) setNextRenewal(next);
      setCancelJustScheduled(true);
      writeLsCancel(sched, next, tier);
      const niceDate = next ? new Date(next).toLocaleDateString() : "the end of this billing cycle";
      alert(`Subscription is cancelled and will expire on ${niceDate}.`);
    } catch {
      alert("Could not cancel plan. Please try again.");
    }
  };

  const enterpriseClick = () => {
    window.location.href = "mailto:sales@yourdomain.com?subject=Enterprise%20Plan%20Inquiry";
  };

  // =========================
  // Banners / Hints
  // =========================
  const BillingUnavailableBanner = () => (
    vpnInfo?.block ? (
      <div className="rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm">
        Billing is unavailable while a VPN/proxy is detected. Please turn it off to upgrade.
      </div>
    ) : null
  );

  const RegionHint = () => (
    (serverCurrency || vpnInfo?.currency) ? (
      <div className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs text-gray-600">
        Billed in <span className="font-medium">{serverCurrency || vpnInfo?.currency}</span>
        {(serverCountry || vpnInfo?.country) && <span>• {serverCountry || vpnInfo?.country}</span>}
      </div>
    ) : null
  );

  const ScheduledNote = () => (
    authed && (cancellationScheduled && nextRenewal) ? (
      <div className="text-xs text-gray-600">
        Subscription is cancelled and will expire on <b>{formatExpiry(nextRenewal)}</b>.
      </div>
    ) : cancelJustScheduled && authed ? (
      <div className="text-xs text-gray-600">
        Subscription is cancelled and will expire at the end of this billing cycle.
      </div>
    ) : null
  );

  // =========================
  // Plan Card
  // =========================
  const PlanCard = ({ p }) => {
    const isEnterprise = p.enterprise;
    const isCurrentPlan = isCurrent(p.id);
    const allowCancelOnCurrent = authed && !cancellationScheduled && isCurrentPlan && (tier === "mini" || tier === "pro");
    const canClick = isEnterprise || isActionableUpgrade(p.id) || allowCancelOnCurrent;
    const disabled = vpnInfo?.block || !authed || !canClick;
    const buttonLabel = isEnterprise ? "Contact sales" : (!authed ? "Login to upgrade" : ctaLabel(p, loadingPlan));
    const Icon = p.icon || Stars;

    return (
      <motion.div
        layout
        whileHover={{ y: -3 }}
        transition={{ type: "spring", stiffness: 260, damping: 20 }}
        className={`relative rounded-3xl border ${p.primary ? "border-indigo-500/70 shadow-[0_10px_30px_-12px_rgba(79,70,229,0.45)]" : "border-gray-200"} bg-white p-6`}
      >
        {p.badge && (
          <span className="absolute -top-3 left-6 inline-flex items-center gap-1 rounded-full bg-indigo-600 px-3 py-1 text-xs font-medium text-white shadow">
            <Sparkles className="h-3.5 w-3.5" /> {p.badge}
          </span>
        )}

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon className={`h-5 w-5 ${p.primary ? "text-indigo-600" : "text-gray-500"}`} />
            <div className={`text-sm font-medium ${p.primary ? "text-indigo-700" : "text-gray-700"}`}>{p.name}</div>
          </div>
          {isCurrentPlan && (
            <TinyBadge className="border-gray-300 bg-gray-50 text-gray-700">Current</TinyBadge>
          )}
        </div>

        <div className="mt-2 flex items-baseline gap-2">
          <div className="text-3xl font-semibold tracking-tight">{p.price}</div>
          {!isEnterprise && <span className="text-xs text-gray-500">/month</span>}
        </div>

        {p.blurb && <p className="mt-1 text-xs text-gray-500">{p.blurb}</p>}

        <div className="mt-3 grid grid-cols-2 gap-2 text-[12px] text-gray-600">
          <div><span className="font-medium">Model:</span> {p.model}</div>
          <div><span className="font-medium">Monthly cap:</span> {fmtNum(p.tokens)}</div>
        </div>

        <ul className="mt-4 space-y-2">
          {p.features.map((f) => <Feature key={f}>{f}</Feature>)}
        </ul>

        {isEnterprise ? (
          <button
            onClick={enterpriseClick}
            className="mt-6 w-full inline-flex justify-center rounded-xl px-4 py-2.5 text-sm font-medium bg-gray-900 text-white hover:bg-black"
          >
            {buttonLabel}
          </button>
        ) : (
          <>
            <button
              disabled={disabled}
              onClick={() => {
                if (isEnterprise) return enterpriseClick();
                if (allowCancelOnCurrent) return cancelPlan();
                if (isActionableUpgrade(p.id)) return startCheckout(p.id);
              }}
              className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${
                disabled
                  ? "bg-gray-200 text-gray-500 cursor-not-allowed"
                  : p.primary
                  ? "bg-indigo-600 text-white hover:bg-indigo-700"
                  : "bg-gray-900 text-white hover:bg-black"
              }`}
              title={
                cancellationScheduled && isCurrentPlan
                  ? `Expires on ${formatExpiry(nextRenewal) || "end of this billing cycle"}`
                  : vpnInfo?.block
                  ? "Disable VPN to upgrade"
                  : !authed
                  ? "Please log in to upgrade"
                  : undefined
              }
            >
              {buttonLabel}
            </button>

            {isCurrentPlan && cancellationScheduled && (
              <div className="mt-2 text-xs text-gray-600">
                Expires on <b>{formatExpiry(nextRenewal) || "end of this billing cycle"}</b>.
              </div>
            )}
          </>
        )}
      </motion.div>
    );
  };

  return (
    <section className="relative">
      {/* Decorative gradient */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-20 -z-10 h-64 bg-gradient-to-b from-indigo-50 via-white to-white"
      />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14">
        {/* BOXED HERO PANEL */}
        <div className="rounded-3xl border border-gray-200 bg-white/70 backdrop-blur p-6 md:p-8 shadow-sm">
          {/* Two-column hero: left = title/subtext, right = meta */}
          <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
            {/* LEFT */}
            <div className="max-w-3xl">
              {/* Badge */}
              <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
                <Stars className="h-3.5 w-3.5" /> Fair, flexible pricing
              </div>

              {/* Heading + subtext */}
              <h1 className="mt-3 text-4xl md:text-5xl lg:text-6xl font-semibold text-gray-900 tracking-tight leading-tight">
                Plans
              </h1>
              <p className="mt-3 text-base md:text-lg text-gray-700 leading-relaxed [text-wrap:balance]">
                Pick a plan that fits your workload. Clear limits, no surprises.
              </p>
            </div>

            {/* RIGHT (moved to the right as requested) */}
            <div className="w-full md:w-auto md:min-w-[320px] flex flex-col items-start md:items-end gap-2">
              {/* Current plan chip */}
              {authed && tier && (
                <div className="inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm bg-white">
                  <span className="text-gray-600">Current plan:</span>
                  <span className="font-medium uppercase">{tier}</span>
                  {cancellationScheduled && nextRenewal && (
                    <span className="ml-1 rounded-full bg-gray-100 border px-2 py-0.5 text-xs text-gray-700">
                      Ends on {formatExpiry(nextRenewal)}
                    </span>
                  )}
                </div>
              )}

              {/* Region chip */}
              <RegionHint />

              {/* Manage / Login chip */}
              {authed && manageUrl ? (
                <a
                  href={manageUrl}
                  className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
                >
                  Manage plan
                </a>
              ) : !authed ? (
                <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700">
                  Please{" "}
                  <Link to="/login" className="underline font-medium">
                    log in
                  </Link>{" "}
                  to upgrade.
                </div>
              ) : null}

              {/* Subscription cancelled note (moved right) */}
              <ScheduledNote />

              {/* VPN banner (kept right for clarity) */}
              <div className="w-full md:w-auto">
                <BillingUnavailableBanner />
              </div>
            </div>
          </div>
        </div>
        {/* END BOXED HERO */}

        <motion.div layout className="mt-10 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
          {plans.map((p) => <PlanCard key={p.id} p={p} />)}
        </motion.div>

        <div className="mt-12 grid gap-4 rounded-2xl border border-gray-200 bg-white p-6 md:grid-cols-2">
          <div className="space-y-2 text-sm text-gray-700">
            <h3 className="font-medium text-gray-900">Billing & Upgrades</h3>
            <p>• Upgrades are immediate and charged in full today. Your billing cycle resets to today → +1 month.</p>
            <p>• Downgrades/cancellations take effect at the next renewal. You keep current plan perks until then.</p>
          </div>
          <div className="space-y-2 text-sm text-gray-700">
            <h3 className="font-medium text-gray-900">Usage & Pricing</h3>
            <p>• Token caps shown are fair-use guardrails; enforcement is server-side.</p>
            <p>• Prices use your region’s billing currency; final price is confirmed during checkout.</p>
          </div>
        </div>
      </div>
    </section>
  );
}



// import React, { useEffect, useMemo, useState } from "react";
// import { Link, useNavigate } from "react-router-dom";
// import secureAxios from "../utils/secureAxios";
// import { motion } from "framer-motion";
// // If you use shadcn/ui, feel free to swap these Tailwind blocks for Cards/Badges/Tooltips.
// // import { Card, CardContent } from "@/components/ui/card";
// // import { Badge } from "@/components/ui/badge";
// // import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
// import { Check, Sparkles, Stars, Shield, Cpu, Globe, GaugeCircle } from "lucide-react";

// // ------------------------------
// // Region + currency detection (client fallback)
// // ------------------------------
// const DETECT_IS_INDIA = () => {
//   try {
//     const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
//     if (tz.toLowerCase().includes("kolkata")) return true;
//     const loc = navigator.language || "";
//     if (/-IN$/i.test(loc)) return true;
//   } catch {}
//   return false;
// };

// // ------------------------------
// // Constants
// // ------------------------------
// const TOKEN_CAP = { free: 200_000, mini: 500_000, pro: 1_000_000 };
// const MODEL_BY_TIER = { free: "gpt-3.5-turbo", mini: "gpt-4o-mini", pro: "gpt-4o" };

// // localStorage helpers to persist "cancellation scheduled" across refresh
// const LS_KEYS = {
//   plan: "cancel_scheduled_plan",           // "free"
//   next: "cancel_next_renewal_iso",         // ISO string
//   tierAtSchedule: "cancel_scheduled_tier", // "mini" | "pro"
// };

// const readLsCancel = () => {
//   try {
//     const plan = localStorage.getItem(LS_KEYS.plan);
//     const next = localStorage.getItem(LS_KEYS.next);
//     const tierAtSchedule = localStorage.getItem(LS_KEYS.tierAtSchedule);
//     return { plan, next, tierAtSchedule };
//   } catch {
//     return { plan: null, next: null, tierAtSchedule: null };
//   }
// };

// const writeLsCancel = (plan, next, tier) => {
//   try {
//     if (plan) localStorage.setItem(LS_KEYS.plan, plan);
//     if (next) localStorage.setItem(LS_KEYS.next, next);
//     if (tier) localStorage.setItem(LS_KEYS.tierAtSchedule, tier);
//   } catch {}
// };

// const clearLsCancel = () => {
//   try {
//     localStorage.removeItem(LS_KEYS.plan);
//     localStorage.removeItem(LS_KEYS.next);
//     localStorage.removeItem(LS_KEYS.tierAtSchedule);
//   } catch {}
// };

// // Format "expires on" date consistently (e.g., 14 Sep 2025)
// const formatExpiry = (iso) => {
//   if (!iso) return null;
//   const d = new Date(iso);
//   if (isNaN(d.getTime())) return null;
//   return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
// };

// // Pretty number
// const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString() : n);

// // Small utility badge
// const TinyBadge = ({ children, className = "" }) => (
//   <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{children}</span>
// );

// // Feature row
// const Feature = ({ children }) => (
//   <li className="flex items-center gap-2 text-sm text-gray-700"><Check className="h-4 w-4" />{children}</li>
// );

// export default function Pricing() {
//   const navigate = useNavigate();

//   // --- Auth & plan state ---
//   const [authed, setAuthed] = useState(false);
//   const [tier, setTier] = useState(null); // 'free' | 'mini' | 'pro' | null
//   const [manageUrl, setManageUrl] = useState(null);

//   // Cancellation scheduling info
//   const [scheduledPlan, setScheduledPlan] = useState(null); // e.g. 'free'
//   const [nextRenewal, setNextRenewal] = useState(null);     // ISO string

//   // Local banner after cancel
//   const [cancelJustScheduled, setCancelJustScheduled] = useState(false);

//   // --- Canonical prices/currency/region from server ---
//   const [serverCurrency, setServerCurrency] = useState(null); // 'INR' | 'USD'
//   const [serverCountry, setServerCountry] = useState(null);   // e.g. 'IN'
//   const [serverPrices, setServerPrices] = useState({
//     mini_minor: 14900,
//     pro_minor: 50000,
//     mini_display: "₹149/mo",
//     pro_display: "₹500/mo",
//   });

//   // --- VPN guard (optional). Fail-open if not present. ---
//   const [vpnInfo, setVpnInfo] = useState({ vpn: false, block: false, reason: "ok", country: null, currency: null });

//   // Heuristic fallback only if server didn't tell us currency yet
//   const initialIsIndia = useMemo(() => DETECT_IS_INDIA(), []);
//   const fallbackCurrency = initialIsIndia ? "INR" : "USD";

//   // Utility: has the stored nextRenewal passed?
//   const isPast = (iso) => {
//     if (!iso) return false;
//     const d = new Date(iso);
//     if (isNaN(d.getTime())) return false;
//     return d.getTime() < Date.now();
//   };

//   // =========================
//   // 1) Probe auth + billing status
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const me = await secureAxios.get("/auth/me"); // non-401
//         const isAuthed = Boolean(me?.data?.authenticated);
//         if (!mounted) return;
//         setAuthed(isAuthed);

//         if (isAuthed) {
//           const s = await secureAxios.get("/billing/status");
//           const t = String(s?.data?.tier || "free").toLowerCase();
//           setTier(t);
//           setManageUrl(s?.data?.manage_url || null);

//           // Server truth (preferred)
//           let serverScheduledPlan = s?.data?.scheduled_plan ? String(s.data.scheduled_plan).toLowerCase() : null;
//           let serverNextRenewal = s?.data?.next_renewal || null;

//           // If server didn't return flags (MVP/older DB), use LS fallback
//           if (!serverScheduledPlan || !serverNextRenewal) {
//             const { plan: lsPlan, next: lsNext, tierAtSchedule } = readLsCancel();
//             const lsLooksValid =
//               lsPlan === "free" && (t === (tierAtSchedule || t)) && !!lsNext && !isPast(lsNext) && (t === "mini" || t === "pro");
//             if (lsLooksValid) {
//               serverScheduledPlan = "free";
//               serverNextRenewal = lsNext;
//             } else {
//               clearLsCancel();
//             }
//           }

//           if (serverScheduledPlan) setScheduledPlan(serverScheduledPlan);
//           if (serverNextRenewal) setNextRenewal(serverNextRenewal);

//           if (!(t === "mini" || t === "pro") || !serverScheduledPlan) {
//             clearLsCancel();
//           }

//           localStorage.setItem("tier", t);
//         } else {
//           setTier(null); setManageUrl(null); setScheduledPlan(null); setNextRenewal(null); localStorage.removeItem("tier"); clearLsCancel();
//         }
//       } catch {
//         if (!mounted) return;
//         setAuthed(false); setTier(null); setManageUrl(null); setScheduledPlan(null); setNextRenewal(null); clearLsCancel();
//       }
//     })();
//     return () => { mounted = false; };
//   }, []);

//   // =========================
//   // 2) Server prices/currency (canonical)
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const { data } = await secureAxios.get("/billing/prices");
//         if (!mounted) return;
//         if (data?.currency) setServerCurrency(data.currency);
//         if (data?.country) setServerCountry(data.country);
//         setServerPrices({
//           mini_minor: data?.mini_minor ?? 14900,
//           pro_minor: data?.pro_minor ?? 50000,
//           mini_display: data?.mini_display ?? "₹149/mo",
//           pro_display: data?.pro_display ?? "₹500/mo",
//         });
//       } catch {}
//     })();
//     return () => { mounted = false; };
//   }, []);

//   // =========================
//   // 3) VPN guard (optional)
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const { data } = await secureAxios.get("/billing/guard");
//         if (!mounted) return;
//         setVpnInfo({
//           vpn: Boolean(data?.vpn),
//           block: Boolean(data?.block),
//           reason: data?.reason || "ok",
//           country: data?.country || serverCountry,
//           currency: data?.currency || serverCurrency,
//         });
//       } catch {}
//     })();
//     return () => { mounted = false; };
//   }, [serverCountry, serverCurrency]);

//   // =========================
//   // Currency to display (no user toggle; server or fallback)
//   // =========================
//   const displayCurrency = serverCurrency || vpnInfo?.currency || fallbackCurrency;
//   const priceFree = "Free"; // never show $0/₹0
//   const priceMini = serverPrices.mini_display;
//   const pricePro = serverPrices.pro_display;

//   // =========================
//   // Plan cards (content)
//   // =========================
//   const plans = [
//     {
//       id: "free",
//       name: "Free",
//       blurb: "Try core features with fair-use limits.",
//       price: priceFree,
//       model: MODEL_BY_TIER.free,
//       tokens: TOKEN_CAP.free,
//       icon: Shield,
//       features: [
//         "20 chats/day",
//         "Session-only search",
//         "Basic OCR",
//         "Uploads: 5 docs/session",
//         "Reference by document name",
//       ],
//     },
//     {
//       id: "mini",
//       name: "Mini+",
//       blurb: "Best for individuals. Faster responses.",
//       price: priceMini,
//       model: MODEL_BY_TIER.mini,
//       tokens: TOKEN_CAP.mini,
//       icon: GaugeCircle,
//       features: [
//         "Unlimited chats (fair use)",
//         "Session-only search",
//         "Faster responses (priority queue)",
//         "Uploads: 20 docs/session",
//         "Basic analytics per chat",
//       ],
//       primary: true,
//       badge: "Most Popular",
//     },
//     {
//       id: "pro",
//       name: "Pro",
//       blurb: "Teams & power users. Global search + exports.",
//       price: pricePro,
//       model: MODEL_BY_TIER.pro,
//       tokens: TOKEN_CAP.pro,
//       icon: Cpu,
//       features: [
//         "Unlimited chats (fair use)",
//         "Global document search (Pro pool)",
//         "Priority queue (fastest)",
//         "Unlimited uploads + Exports (PDF/JSON/MD)",
//         "Usage analytics dashboard",
//       ],
//     },
//     {
//       id: "enterprise",
//       name: "Enterprise",
//       blurb: "Scale securely with SSO, SLAs and support.",
//       price: "Custom",
//       model: "Custom",
//       tokens: "Custom",
//       icon: Globe,
//       features: [
//         "Multi-seat & Admin controls",
//         "Bulk ingestion & API",
//         "SSO & SLA",
//         "Dedicated support",
//       ],
//       enterprise: true,
//     },
//   ];

//   // =========================
//   // CTA logic (per rules)
//   // =========================
//   const isCurrent = (id) => authed && tier && id === tier;
//   const cancellationScheduled = authed && String(scheduledPlan || "").toLowerCase() === "free";

//   const isActionableUpgrade = (planId) => {
//     if (!authed) return false;
//     if (vpnInfo?.block) return false;
//     if (planId === "enterprise") return false;
//     if (tier === "free" && (planId === "mini" || planId === "pro")) return true;
//     if (tier === "mini" && planId === "pro") return true;
//     return false;
//   };

//   const ctaLabel = (plan, loadingPlan) => {
//     if (!authed) return "Login to upgrade";
//     if (plan.enterprise) return "Contact sales";
//     if (isCurrent(plan.id)) {
//       if (cancellationScheduled) return "Cancellation scheduled";
//       if (tier === "mini" || tier === "pro") return "Cancel plan";
//       return "Current plan";
//     }
//     if (isActionableUpgrade(plan.id)) return loadingPlan === plan.id ? "Redirecting…" : "Upgrade";
//     if (tier === "pro" && plan.id === "mini") return "Downgrade at renewal";
//     if (tier === "mini" && plan.id === "free") return "Downgrade at renewal";
//     if (tier === "pro" && plan.id === "free") return "Cancel at renewal";
//     return "Get started";
//   };

//   // =========================
//   // Actions
//   // =========================
//   const [loadingPlan, setLoadingPlan] = useState(null);

//   const startCheckout = async (planId) => {
//     try {
//       if (!authed) { navigate("/login"); return; }
//       if (vpnInfo?.block) { alert("Billing is disabled while VPN/proxy is detected. Please disable VPN and retry."); return; }
//       if (!isActionableUpgrade(planId)) return;

//       setLoadingPlan(planId);
//       const { data } = await secureAxios.post("/billing/checkout", { plan: planId });
//       if (data?.url) { window.location.href = data.url; }
//       else { alert("Could not start checkout. Please try again."); }
//     } catch (e) {
//       console.error(e);
//       const msg = typeof e?.response?.data?.detail === "object"
//         ? JSON.stringify(e.response.data.detail)
//         : e?.response?.data?.detail || "Checkout failed. Please try again.";
//       alert(msg);
//     } finally {
//       setLoadingPlan(null);
//     }
//   };

//   const cancelPlan = async () => {
//     try {
//       const { data } = await secureAxios.post("/billing/cancel", { mode: "period_end" });
//       const sched = data?.scheduled_plan ? String(data.scheduled_plan).toLowerCase() : "free";
//       const next = data?.next_renewal || null;
//       setScheduledPlan(sched);
//       if (next) setNextRenewal(next);
//       setCancelJustScheduled(true);
//       writeLsCancel(sched, next, tier);
//       const niceDate = next ? new Date(next).toLocaleDateString() : "the end of this billing cycle";
//       alert(`Subscription is cancelled and will expire on ${niceDate}.`);
//     } catch {
//       alert("Could not cancel plan. Please try again.");
//     }
//   };

//   const enterpriseClick = () => {
//     window.location.href = "mailto:sales@yourdomain.com?subject=Enterprise%20Plan%20Inquiry";
//   };

//   // =========================
//   // Banners
//   // =========================
//   const BillingUnavailableBanner = () => (
//     vpnInfo?.block ? (
//       <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm">
//         {/* Option A wording */}
//         Billing is unavailable while a VPN/proxy is detected. Please turn it off to upgrade.
//       </div>
//     ) : null
//   );

//   const RegionHint = () => (
//     (serverCurrency || vpnInfo?.currency) ? (
//       <div className="mt-2 text-xs text-gray-500">
//         {/* Option A wording */}
//         Billed in <span className="font-medium">{serverCurrency || vpnInfo?.currency}</span>
//         {serverCountry || vpnInfo?.country ? ` • Region: ${serverCountry || vpnInfo?.country}` : null}
//       </div>
//     ) : null
//   );

//   const ScheduledNote = () => (
//     authed && (cancellationScheduled && nextRenewal) ? (
//       <div className="mt-2 text-xs text-gray-600">Subscription is cancelled and will expire on <b>{formatExpiry(nextRenewal)}</b>.</div>
//     ) : cancelJustScheduled && authed ? (
//       <div className="mt-2 text-xs text-gray-600">Subscription is cancelled and will expire at the end of this billing cycle.</div>
//     ) : null
//   );

//   // =========================
//   // Render helpers
//   // =========================
//   const PlanCard = ({ p }) => {
//     const isEnterprise = p.enterprise;
//     const isCurrentPlan = isCurrent(p.id);
//     const allowCancelOnCurrent = authed && !cancellationScheduled && isCurrentPlan && (tier === "mini" || tier === "pro");
//     const canClick = isEnterprise || isActionableUpgrade(p.id) || allowCancelOnCurrent;
//     const disabled = vpnInfo?.block || !authed || !canClick;
//     const buttonLabel = isEnterprise ? "Contact sales" : (!authed ? "Login to upgrade" : ctaLabel(p, loadingPlan));
//     const Icon = p.icon || Stars;

//     return (
//       <motion.div
//         layout
//         whileHover={{ y: -3 }}
//         transition={{ type: "spring", stiffness: 260, damping: 20 }}
//         className={`relative rounded-3xl border ${p.primary ? "border-indigo-500/70 shadow-[0_10px_30px_-12px_rgba(79,70,229,0.45)]" : "border-gray-200"} bg-white p-6`}
//       >
//         {p.badge && (
//           <span className="absolute -top-3 left-6 inline-flex items-center gap-1 rounded-full bg-indigo-600 px-3 py-1 text-xs font-medium text-white shadow"> 
//             <Sparkles className="h-3.5 w-3.5" /> {p.badge}
//           </span>
//         )}

//         <div className="flex items-center justify-between">
//           <div className="flex items-center gap-2">
//             <Icon className={`h-5 w-5 ${p.primary ? "text-indigo-600" : "text-gray-500"}`} />
//             <div className={`text-sm font-medium ${p.primary ? "text-indigo-700" : "text-gray-700"}`}>{p.name}</div>
//           </div>
//           {isCurrentPlan && (
//             <TinyBadge className="border-gray-300 bg-gray-50 text-gray-700">Current</TinyBadge>
//           )}
//         </div>

//         <div className="mt-2 flex items-baseline gap-2">
//           <div className="text-3xl font-semibold tracking-tight">{p.price}</div>
//           {!isEnterprise && (
//             <span className="text-xs text-gray-500">/month</span>
//           )}
//         </div>
//         {p.blurb && <p className="mt-1 text-xs text-gray-500">{p.blurb}</p>}

//         <div className="mt-3 grid grid-cols-2 gap-2 text-[12px] text-gray-600">
//           <div><span className="font-medium">Model:</span> {p.model}</div>
//           <div><span className="font-medium">Monthly cap:</span> {fmtNum(p.tokens)}</div>
//         </div>

//         <ul className="mt-4 space-y-2">
//           {p.features.map((f) => <Feature key={f}>{f}</Feature>)}
//         </ul>

//         {isEnterprise ? (
//           <button onClick={enterpriseClick} className="mt-6 w-full inline-flex justify-center rounded-xl px-4 py-2.5 text-sm font-medium bg-gray-900 text-white hover:bg-black">
//             {buttonLabel}
//           </button>
//         ) : (
//           <>
//             <button
//               disabled={disabled}
//               onClick={() => {
//                 if (isEnterprise) return enterpriseClick();
//                 if (allowCancelOnCurrent) return cancelPlan();
//                 if (isActionableUpgrade(p.id)) return startCheckout(p.id);
//               }}
//               className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${disabled ? "bg-gray-200 text-gray-500 cursor-not-allowed" : p.primary ? "bg-indigo-600 text-white hover:bg-indigo-700" : "bg-gray-900 text-white hover:bg-black"}`}
//               title={
//                 cancellationScheduled && isCurrentPlan ? `Expires on ${formatExpiry(nextRenewal) || "end of this billing cycle"}` :
//                 vpnInfo?.block ? "Disable VPN to upgrade" :
//                 !authed ? "Please log in to upgrade" : undefined
//               }
//             >
//               {buttonLabel}
//             </button>
//             {isCurrentPlan && cancellationScheduled && (
//               <div className="mt-2 text-xs text-gray-600">
//                 {/* Option A wording for cancellation chip */}
//                 Ends on <b>{formatExpiry(nextRenewal) || "end of this billing cycle"}</b>.
//               </div>
//             )}
//           </>
//         )}
//       </motion.div>
//     );
//   };

//   return (
//     <section className="relative">
//       {/* Decorative gradient */}
//       <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-20 -z-10 h-64 bg-gradient-to-b from-indigo-50 via-white to-white" />

//       <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14">
//         <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
//           <div>
//             {/* Option A badge */}
//             <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
//               <Stars className="h-3.5 w-3.5" /> Fair, flexible pricing
//             </div>

//             {/* Option A H1 + subtext */}
//             <h1 className="mt-3 text-3xl font-semibold text-gray-900 tracking-tight">Choose your plan</h1>
//             <p className="mt-2 max-w-2xl text-gray-700">Pick a plan that fits your workload. Clear limits, no surprises.</p>

//             {/* Current plan (only if authenticated) */}
//             {authed && tier && (
//               <div className="mt-3 inline-flex items-center gap-2 rounded-full border px-4 py-1 text-sm">
//                 <span className="text-gray-600">Current plan:</span>
//                 <span className="font-medium uppercase">{tier}</span>
//                 {cancellationScheduled && nextRenewal && (
//                   <span className="ml-1 rounded-full bg-gray-100 border px-2 py-0.5 text-xs text-gray-700">
//                     {/* Option A wording */}
//                     Ends on {formatExpiry(nextRenewal)}
//                   </span>
//                 )}
//               </div>
//             )}

//             <RegionHint />
//             <BillingUnavailableBanner />
//             <ScheduledNote />

//             {!authed && (
//               <div className="mt-4 text-sm text-gray-700">
//                 Please <Link to="/login" className="underline font-medium">log in</Link> to upgrade.
//               </div>
//             )}
//           </div>

//           {/* Optional manage link */}
//           {authed && manageUrl && (
//             <a href={manageUrl} className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium shadow-sm hover:bg-gray-50">
//               Manage plan
//             </a>
//           )}
//         </div>

//         <motion.div layout className="mt-8 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
//           {plans.map((p) => <PlanCard key={p.id} p={p} />)}
//         </motion.div>

//         <div className="mt-12 grid gap-4 rounded-2xl border border-gray-200 bg-white p-6 md:grid-cols-2">
//           <div className="space-y-2 text-sm text-gray-700">
//             <h3 className="font-medium text-gray-900">Billing & Upgrades</h3>
//             <p>• Upgrades are immediate and charged in full today. Your billing cycle resets to today → +1 month.</p>
//             <p>• Downgrades/cancellations take effect at the next renewal. You keep current plan perks until then.</p>
//           </div>
//           <div className="space-y-2 text-sm text-gray-700">
//             <h3 className="font-medium text-gray-900">Usage & Pricing</h3>
//             <p>• Token caps shown are fair-use guardrails; enforcement is server-side.</p>
//             <p>• Prices use your region’s billing currency; final price is confirmed during checkout.</p>
//           </div>
//         </div>
//       </div>
//     </section>
//   );
// }



// import React, { useEffect, useMemo, useState } from "react";
// import { Link, useNavigate } from "react-router-dom";
// import secureAxios from "../utils/secureAxios";
// import { motion } from "framer-motion";
// // If you use shadcn/ui, feel free to swap these Tailwind blocks for Cards/Badges/Tooltips.
// // import { Card, CardContent } from "@/components/ui/card";
// // import { Badge } from "@/components/ui/badge";
// // import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
// import { Check, Sparkles, Stars, Shield, Cpu, Globe, GaugeCircle, Upload, Ban, CircleHelp } from "lucide-react";

// // ------------------------------
// // Region + currency detection (client fallback)
// // ------------------------------
// const DETECT_IS_INDIA = () => {
//   try {
//     const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
//     if (tz.toLowerCase().includes("kolkata")) return true;
//     const loc = navigator.language || "";
//     if (/-IN$/i.test(loc)) return true;
//   } catch {}
//   return false;
// };

// // ------------------------------
// // Constants
// // ------------------------------
// const TOKEN_CAP = { free: 200_000, mini: 500_000, pro: 1_000_000 };
// const MODEL_BY_TIER = { free: "gpt-3.5-turbo", mini: "gpt-4o-mini", pro: "gpt-4o" };

// // localStorage helpers to persist "cancellation scheduled" across refresh
// const LS_KEYS = {
//   plan: "cancel_scheduled_plan",           // "free"
//   next: "cancel_next_renewal_iso",         // ISO string
//   tierAtSchedule: "cancel_scheduled_tier", // "mini" | "pro"
// };

// const readLsCancel = () => {
//   try {
//     const plan = localStorage.getItem(LS_KEYS.plan);
//     const next = localStorage.getItem(LS_KEYS.next);
//     const tierAtSchedule = localStorage.getItem(LS_KEYS.tierAtSchedule);
//     return { plan, next, tierAtSchedule };
//   } catch {
//     return { plan: null, next: null, tierAtSchedule: null };
//   }
// };

// const writeLsCancel = (plan, next, tier) => {
//   try {
//     if (plan) localStorage.setItem(LS_KEYS.plan, plan);
//     if (next) localStorage.setItem(LS_KEYS.next, next);
//     if (tier) localStorage.setItem(LS_KEYS.tierAtSchedule, tier);
//   } catch {}
// };

// const clearLsCancel = () => {
//   try {
//     localStorage.removeItem(LS_KEYS.plan);
//     localStorage.removeItem(LS_KEYS.next);
//     localStorage.removeItem(LS_KEYS.tierAtSchedule);
//   } catch {}
// };

// // Format "expires on" date consistently (e.g., 14 Sep 2025)
// const formatExpiry = (iso) => {
//   if (!iso) return null;
//   const d = new Date(iso);
//   if (isNaN(d.getTime())) return null;
//   return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
// };

// // Pretty number
// const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString() : n);

// // Small utility badge
// const TinyBadge = ({ children, className = "" }) => (
//   <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{children}</span>
// );

// // Feature row
// const Feature = ({ children }) => (
//   <li className="flex items-center gap-2 text-sm text-gray-700"><Check className="h-4 w-4" />{children}</li>
// );

// export default function Pricing() {
//   const navigate = useNavigate();

//   // --- Auth & plan state ---
//   const [authed, setAuthed] = useState(false);
//   const [tier, setTier] = useState(null); // 'free' | 'mini' | 'pro' | null
//   const [manageUrl, setManageUrl] = useState(null);

//   // Cancellation scheduling info
//   const [scheduledPlan, setScheduledPlan] = useState(null); // e.g. 'free'
//   const [nextRenewal, setNextRenewal] = useState(null);     // ISO string

//   // Local banner after cancel
//   const [cancelJustScheduled, setCancelJustScheduled] = useState(false);

//   // --- Canonical prices/currency/region from server ---
//   const [serverCurrency, setServerCurrency] = useState(null); // 'INR' | 'USD'
//   const [serverCountry, setServerCountry] = useState(null);   // e.g. 'IN'
//   const [serverPrices, setServerPrices] = useState({
//     mini_minor: 14900,
//     pro_minor: 50000,
//     mini_display: "₹149/mo",
//     pro_display: "₹500/mo",
//   });

//   // --- VPN guard (optional). Fail-open if not present. ---
//   const [vpnInfo, setVpnInfo] = useState({ vpn: false, block: false, reason: "ok", country: null, currency: null });

//   // Heuristic fallback only if server didn't tell us currency yet
//   const initialIsIndia = useMemo(() => DETECT_IS_INDIA(), []);
//   const fallbackCurrency = initialIsIndia ? "INR" : "USD";

//   // Utility: has the stored nextRenewal passed?
//   const isPast = (iso) => {
//     if (!iso) return false;
//     const d = new Date(iso);
//     if (isNaN(d.getTime())) return false;
//     return d.getTime() < Date.now();
//   };

//   // =========================
//   // 1) Probe auth + billing status
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const me = await secureAxios.get("/auth/me"); // non-401
//         const isAuthed = Boolean(me?.data?.authenticated);
//         if (!mounted) return;
//         setAuthed(isAuthed);

//         if (isAuthed) {
//           const s = await secureAxios.get("/billing/status");
//           const t = String(s?.data?.tier || "free").toLowerCase();
//           setTier(t);
//           setManageUrl(s?.data?.manage_url || null);

//           // Server truth (preferred)
//           let serverScheduledPlan = s?.data?.scheduled_plan ? String(s.data.scheduled_plan).toLowerCase() : null;
//           let serverNextRenewal = s?.data?.next_renewal || null;

//           // If server didn't return flags (MVP/older DB), use LS fallback
//           if (!serverScheduledPlan || !serverNextRenewal) {
//             const { plan: lsPlan, next: lsNext, tierAtSchedule } = readLsCancel();
//             const lsLooksValid =
//               lsPlan === "free" && (t === (tierAtSchedule || t)) && !!lsNext && !isPast(lsNext) && (t === "mini" || t === "pro");
//             if (lsLooksValid) {
//               serverScheduledPlan = "free";
//               serverNextRenewal = lsNext;
//             } else {
//               clearLsCancel();
//             }
//           }

//           if (serverScheduledPlan) setScheduledPlan(serverScheduledPlan);
//           if (serverNextRenewal) setNextRenewal(serverNextRenewal);

//           if (!(t === "mini" || t === "pro") || !serverScheduledPlan) {
//             clearLsCancel();
//           }

//           localStorage.setItem("tier", t);
//         } else {
//           setTier(null); setManageUrl(null); setScheduledPlan(null); setNextRenewal(null); localStorage.removeItem("tier"); clearLsCancel();
//         }
//       } catch {
//         if (!mounted) return;
//         setAuthed(false); setTier(null); setManageUrl(null); setScheduledPlan(null); setNextRenewal(null); clearLsCancel();
//       }
//     })();
//     return () => { mounted = false; };
//   }, []);

//   // =========================
//   // 2) Server prices/currency (canonical)
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const { data } = await secureAxios.get("/billing/prices");
//         if (!mounted) return;
//         if (data?.currency) setServerCurrency(data.currency);
//         if (data?.country) setServerCountry(data.country);
//         setServerPrices({
//           mini_minor: data?.mini_minor ?? 14900,
//           pro_minor: data?.pro_minor ?? 50000,
//           mini_display: data?.mini_display ?? "₹149/mo",
//           pro_display: data?.pro_display ?? "₹500/mo",
//         });
//       } catch {}
//     })();
//     return () => { mounted = false; };
//   }, []);

//   // =========================
//   // 3) VPN guard (optional)
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const { data } = await secureAxios.get("/billing/guard");
//         if (!mounted) return;
//         setVpnInfo({
//           vpn: Boolean(data?.vpn),
//           block: Boolean(data?.block),
//           reason: data?.reason || "ok",
//           country: data?.country || serverCountry,
//           currency: data?.currency || serverCurrency,
//         });
//       } catch {}
//     })();
//     return () => { mounted = false; };
//   }, [serverCountry, serverCurrency]);

//   // =========================
//   // Currency to display (no user toggle; server or fallback)
//   // =========================
//   const displayCurrency = serverCurrency || vpnInfo?.currency || fallbackCurrency;
//   const priceFree = "Free"; // never show $0/₹0
//   const priceMini = serverPrices.mini_display;
//   const pricePro = serverPrices.pro_display;

//   // =========================
//   // Plan cards (content)
//   // =========================
//   const plans = [
//     {
//       id: "free",
//       name: "Free",
//       blurb: "Try core features with fair-use limits.",
//       price: priceFree,
//       model: MODEL_BY_TIER.free,
//       tokens: TOKEN_CAP.free,
//       icon: Shield,
//       features: [
//         "20 chats/day",
//         "Session-only search",
//         "Basic OCR",
//         "Uploads: 5 docs/session",
//         "Reference by document name",
//       ],
//     },
//     {
//       id: "mini",
//       name: "Mini+",
//       blurb: "Best for individuals. Faster responses.",
//       price: priceMini,
//       model: MODEL_BY_TIER.mini,
//       tokens: TOKEN_CAP.mini,
//       icon: GaugeCircle,
//       features: [
//         "Unlimited chats (fair use)",
//         "Session-only search",
//         "Faster responses (priority queue)",
//         "Uploads: 20 docs/session",
//         "Basic analytics per chat",
//       ],
//       primary: true,
//       badge: "Most Popular",
//     },
//     {
//       id: "pro",
//       name: "Pro",
//       blurb: "Teams & power users. Global search + exports.",
//       price: pricePro,
//       model: MODEL_BY_TIER.pro,
//       tokens: TOKEN_CAP.pro,
//       icon: Cpu,
//       features: [
//         "Unlimited chats (fair use)",
//         "Global document search (Pro pool)",
//         "Priority queue (fastest)",
//         "Unlimited uploads + Exports (PDF/JSON/MD)",
//         "Usage analytics dashboard",
//       ],
//     },
//     {
//       id: "enterprise",
//       name: "Enterprise",
//       blurb: "Scale securely with SSO, SLAs and support.",
//       price: "Custom",
//       model: "Custom",
//       tokens: "Custom",
//       icon: Globe,
//       features: [
//         "Multi-seat & Admin controls",
//         "Bulk ingestion & API",
//         "SSO & SLA",
//         "Dedicated support",
//       ],
//       enterprise: true,
//     },
//   ];

//   // =========================
//   // CTA logic (per rules)
//   // =========================
//   const isCurrent = (id) => authed && tier && id === tier;
//   const cancellationScheduled = authed && String(scheduledPlan || "").toLowerCase() === "free";

//   const isActionableUpgrade = (planId) => {
//     if (!authed) return false;
//     if (vpnInfo?.block) return false;
//     if (planId === "enterprise") return false;
//     if (tier === "free" && (planId === "mini" || planId === "pro")) return true;
//     if (tier === "mini" && planId === "pro") return true;
//     return false;
//   };

//   const ctaLabel = (plan, loadingPlan) => {
//     if (!authed) return "Login to upgrade";
//     if (plan.enterprise) return "Contact sales";
//     if (isCurrent(plan.id)) {
//       if (cancellationScheduled) return "Cancellation scheduled";
//       if (tier === "mini" || tier === "pro") return "Cancel plan";
//       return "Current plan";
//     }
//     if (isActionableUpgrade(plan.id)) return loadingPlan === plan.id ? "Redirecting…" : "Upgrade";
//     if (tier === "pro" && plan.id === "mini") return "Downgrade at renewal";
//     if (tier === "mini" && plan.id === "free") return "Downgrade at renewal";
//     if (tier === "pro" && plan.id === "free") return "Cancel at renewal";
//     return "Get started";
//   };

//   // =========================
//   // Actions
//   // =========================
//   const [loadingPlan, setLoadingPlan] = useState(null);

//   const startCheckout = async (planId) => {
//     try {
//       if (!authed) { navigate("/login"); return; }
//       if (vpnInfo?.block) { alert("Billing is disabled while VPN/proxy is detected. Please disable VPN and retry."); return; }
//       if (!isActionableUpgrade(planId)) return;

//       setLoadingPlan(planId);
//       const { data } = await secureAxios.post("/billing/checkout", { plan: planId });
//       if (data?.url) { window.location.href = data.url; }
//       else { alert("Could not start checkout. Please try again."); }
//     } catch (e) {
//       console.error(e);
//       const msg = typeof e?.response?.data?.detail === "object"
//         ? JSON.stringify(e.response.data.detail)
//         : e?.response?.data?.detail || "Checkout failed. Please try again.";
//       alert(msg);
//     } finally {
//       setLoadingPlan(null);
//     }
//   };

//   const cancelPlan = async () => {
//     try {
//       const { data } = await secureAxios.post("/billing/cancel", { mode: "period_end" });
//       const sched = data?.scheduled_plan ? String(data.scheduled_plan).toLowerCase() : "free";
//       const next = data?.next_renewal || null;
//       setScheduledPlan(sched);
//       if (next) setNextRenewal(next);
//       setCancelJustScheduled(true);
//       writeLsCancel(sched, next, tier);
//       const niceDate = next ? new Date(next).toLocaleDateString() : "the end of this billing cycle";
//       alert(`Subscription is cancelled and will expire on ${niceDate}.`);
//     } catch {
//       alert("Could not cancel plan. Please try again.");
//     }
//   };

//   const enterpriseClick = () => {
//     window.location.href = "mailto:sales@yourdomain.com?subject=Enterprise%20Plan%20Inquiry";
//   };

//   // =========================
//   // Banners
//   // =========================
//   const BillingUnavailableBanner = () => (
//     vpnInfo?.block ? (
//       <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm">
//         Billing temporarily unavailable while a VPN/proxy is detected. Disable VPN to upgrade.
//       </div>
//     ) : null
//   );

//   const RegionHint = () => (
//     (serverCurrency || vpnInfo?.currency) ? (
//       <div className="mt-2 text-xs text-gray-500">
//         Billing currency: <span className="font-medium">{serverCurrency || vpnInfo?.currency}</span>
//         {serverCountry || vpnInfo?.country ? ` • Region: ${serverCountry || vpnInfo?.country}` : null}
//       </div>
//     ) : null
//   );

//   const ScheduledNote = () => (
//     authed && (cancellationScheduled && nextRenewal) ? (
//       <div className="mt-2 text-xs text-gray-600">Subscription is cancelled and will expire on <b>{formatExpiry(nextRenewal)}</b>.</div>
//     ) : cancelJustScheduled && authed ? (
//       <div className="mt-2 text-xs text-gray-600">Subscription is cancelled and will expire at the end of this billing cycle.</div>
//     ) : null
//   );

//   // =========================
//   // Render helpers
//   // =========================
//   const PlanCard = ({ p }) => {
//     const isEnterprise = p.enterprise;
//     const isCurrentPlan = isCurrent(p.id);
//     const allowCancelOnCurrent = authed && !cancellationScheduled && isCurrentPlan && (tier === "mini" || tier === "pro");
//     const canClick = isEnterprise || isActionableUpgrade(p.id) || allowCancelOnCurrent;
//     const disabled = vpnInfo?.block || !authed || !canClick;
//     const buttonLabel = isEnterprise ? "Contact sales" : (!authed ? "Login to upgrade" : ctaLabel(p, loadingPlan));
//     const Icon = p.icon || Stars;

//     return (
//       <motion.div
//         layout
//         whileHover={{ y: -3 }}
//         transition={{ type: "spring", stiffness: 260, damping: 20 }}
//         className={`relative rounded-3xl border ${p.primary ? "border-indigo-500/70 shadow-[0_10px_30px_-12px_rgba(79,70,229,0.45)]" : "border-gray-200"} bg-white p-6`}
//       >
//         {p.badge && (
//           <span className="absolute -top-3 left-6 inline-flex items-center gap-1 rounded-full bg-indigo-600 px-3 py-1 text-xs font-medium text-white shadow"> 
//             <Sparkles className="h-3.5 w-3.5" /> {p.badge}
//           </span>
//         )}

//         <div className="flex items-center justify-between">
//           <div className="flex items-center gap-2">
//             <Icon className={`h-5 w-5 ${p.primary ? "text-indigo-600" : "text-gray-500"}`} />
//             <div className={`text-sm font-medium ${p.primary ? "text-indigo-700" : "text-gray-700"}`}>{p.name}</div>
//           </div>
//           {isCurrentPlan && (
//             <TinyBadge className="border-gray-300 bg-gray-50 text-gray-700">Current</TinyBadge>
//           )}
//         </div>

//         <div className="mt-2 flex items-baseline gap-2">
//           <div className="text-3xl font-semibold tracking-tight">{p.price}</div>
//           {!isEnterprise && (
//             <span className="text-xs text-gray-500">/month</span>
//           )}
//         </div>
//         {p.blurb && <p className="mt-1 text-xs text-gray-500">{p.blurb}</p>}

//         <div className="mt-3 grid grid-cols-2 gap-2 text-[12px] text-gray-600">
//           <div><span className="font-medium">Model:</span> {p.model}</div>
//           <div><span className="font-medium">Monthly cap:</span> {fmtNum(p.tokens)}</div>
//         </div>

//         <ul className="mt-4 space-y-2">
//           {p.features.map((f) => <Feature key={f}>{f}</Feature>)}
//         </ul>

//         {isEnterprise ? (
//           <button onClick={enterpriseClick} className="mt-6 w-full inline-flex justify-center rounded-xl px-4 py-2.5 text-sm font-medium bg-gray-900 text-white hover:bg-black">
//             {buttonLabel}
//           </button>
//         ) : (
//           <>
//             <button
//               disabled={disabled}
//               onClick={() => {
//                 if (isEnterprise) return enterpriseClick();
//                 if (allowCancelOnCurrent) return cancelPlan();
//                 if (isActionableUpgrade(p.id)) return startCheckout(p.id);
//               }}
//               className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${disabled ? "bg-gray-200 text-gray-500 cursor-not-allowed" : p.primary ? "bg-indigo-600 text-white hover:bg-indigo-700" : "bg-gray-900 text-white hover:bg-black"}`}
//               title={
//                 cancellationScheduled && isCurrentPlan ? `Expires on ${formatExpiry(nextRenewal) || "end of this billing cycle"}` :
//                 vpnInfo?.block ? "Disable VPN to upgrade" :
//                 !authed ? "Please log in to upgrade" : undefined
//               }
//             >
//               {buttonLabel}
//             </button>
//             {isCurrentPlan && cancellationScheduled && (
//               <div className="mt-2 text-xs text-gray-600">Expires on <b>{formatExpiry(nextRenewal) || "end of this billing cycle"}</b>.</div>
//             )}
//           </>
//         )}
//       </motion.div>
//     );
//   };

//   return (
//     <section className="relative">
//       {/* Decorative gradient */}
//       <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-20 -z-10 h-64 bg-gradient-to-b from-indigo-50 via-white to-white" />

//       <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14">
//         <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
//           <div>
//             <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
//               <Stars className="h-3.5 w-3.5" /> Simple, transparent pricing
//             </div>
//             <h1 className="mt-3 text-3xl font-semibold text-gray-900 tracking-tight">Pricing</h1>
//             <p className="mt-2 max-w-2xl text-gray-700">Plans that scale with your work—switch anytime. No hidden fees.</p>

//             {/* Current plan (only if authenticated) */}
//             {authed && tier && (
//               <div className="mt-3 inline-flex items-center gap-2 rounded-full border px-4 py-1 text-sm">
//                 <span className="text-gray-600">Current plan:</span>
//                 <span className="font-medium uppercase">{tier}</span>
//                 {cancellationScheduled && nextRenewal && (
//                   <span className="ml-1 rounded-full bg-gray-100 border px-2 py-0.5 text-xs text-gray-700">Cancels on {formatExpiry(nextRenewal)}</span>
//                 )}
//               </div>
//             )}

//             <RegionHint />
//             <BillingUnavailableBanner />
//             <ScheduledNote />

//             {!authed && (
//               <div className="mt-4 text-sm text-gray-700">
//                 Please <Link to="/login" className="underline font-medium">log in</Link> to upgrade.
//               </div>
//             )}
//           </div>

//           {/* Optional manage link */}
//           {authed && manageUrl && (
//             <a href={manageUrl} className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium shadow-sm hover:bg-gray-50">
//               Manage plan
//             </a>
//           )}
//         </div>

//         <motion.div layout className="mt-8 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
//           {plans.map((p) => <PlanCard key={p.id} p={p} />)}
//         </motion.div>

//         <div className="mt-12 grid gap-4 rounded-2xl border border-gray-200 bg-white p-6 md:grid-cols-2">
//           <div className="space-y-2 text-sm text-gray-700">
//             <h3 className="font-medium text-gray-900">Billing & Upgrades</h3>
//             <p>• Upgrades are immediate and charged in full today. Your billing cycle resets to today → +1 month.</p>
//             <p>• Downgrades/cancellations take effect at the next renewal. You keep current plan perks until then.</p>
//           </div>
//           <div className="space-y-2 text-sm text-gray-700">
//             <h3 className="font-medium text-gray-900">Usage & Pricing</h3>
//             <p>• Token caps shown are fair-use guardrails; enforcement is server-side.</p>
//             <p>• Prices use your region’s billing currency; final price is confirmed during checkout.</p>
//           </div>
//         </div>
//       </div>
//     </section>
//   );
// }




// import React, { useEffect, useMemo, useState } from "react";
// import { Link, useNavigate } from "react-router-dom";
// import secureAxios from "../utils/secureAxios";

// // Server is canonical for currency/prices.
// // Light client heuristic is only a visual fallback if server doesn't answer.
// const DETECT_IS_INDIA = () => {
//   try {
//     const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
//     if (tz.toLowerCase().includes("kolkata")) return true;
//     const loc = navigator.language || "";
//     if (/-IN$/i.test(loc)) return true;
//   } catch {}
//   return false;
// };

// const TOKEN_CAP = { free: 200_000, mini: 500_000, pro: 1_000_000 };
// const MODEL_BY_TIER = { free: "gpt-3.5-turbo", mini: "gpt-4o-mini", pro: "gpt-4o" };

// // ---- localStorage helpers to persist "cancellation scheduled" across refresh ----
// const LS_KEYS = {
//   plan: "cancel_scheduled_plan",           // "free"
//   next: "cancel_next_renewal_iso",         // ISO string
//   tierAtSchedule: "cancel_scheduled_tier", // "mini" | "pro"
// };

// const readLsCancel = () => {
//   try {
//     const plan = localStorage.getItem(LS_KEYS.plan);
//     const next = localStorage.getItem(LS_KEYS.next);
//     const tierAtSchedule = localStorage.getItem(LS_KEYS.tierAtSchedule);
//     return { plan, next, tierAtSchedule };
//   } catch {
//     return { plan: null, next: null, tierAtSchedule: null };
//   }
// };

// const writeLsCancel = (plan, next, tier) => {
//   try {
//     if (plan) localStorage.setItem(LS_KEYS.plan, plan);
//     if (next) localStorage.setItem(LS_KEYS.next, next);
//     if (tier) localStorage.setItem(LS_KEYS.tierAtSchedule, tier);
//   } catch {}
// };

// const clearLsCancel = () => {
//   try {
//     localStorage.removeItem(LS_KEYS.plan);
//     localStorage.removeItem(LS_KEYS.next);
//     localStorage.removeItem(LS_KEYS.tierAtSchedule);
//   } catch {}
// };

// // Format "expires on" date consistently (e.g., 14 Sep 2025)
// const formatExpiry = (iso) => {
//   if (!iso) return null;
//   const d = new Date(iso);
//   if (isNaN(d.getTime())) return null;
//   return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
// };

// export default function Pricing() {
//   const navigate = useNavigate();

//   // --- Auth & plan state ---
//   const [authed, setAuthed] = useState(false);
//   const [tier, setTier] = useState(null); // 'free' | 'mini' | 'pro' | null
//   const [manageUrl, setManageUrl] = useState(null);

//   // Cancellation scheduling info
//   const [scheduledPlan, setScheduledPlan] = useState(null); // e.g. 'free'
//   const [nextRenewal, setNextRenewal] = useState(null);     // ISO string

//   // Local banner after cancel (UX hint for first page load right after cancel)
//   const [cancelJustScheduled, setCancelJustScheduled] = useState(false);

//   // --- Canonical prices/currency/region from server ---
//   const [serverCurrency, setServerCurrency] = useState(null); // 'INR' | 'USD'
//   const [serverCountry, setServerCountry] = useState(null);   // e.g. 'IN'
//   const [serverPrices, setServerPrices] = useState({
//     mini_minor: 14900,
//     pro_minor: 50000,
//     mini_display: "₹149/mo",
//     pro_display: "₹500/mo",
//   });

//   // --- VPN guard (optional). Fail-open if not present. ---
//   const [vpnInfo, setVpnInfo] = useState({
//     vpn: false,
//     block: false,
//     reason: "ok",
//     country: null,
//     currency: null,
//   });

//   // Heuristic fallback only if server didn't tell us currency yet
//   const initialIsIndia = useMemo(() => DETECT_IS_INDIA(), []);
//   const fallbackCurrency = initialIsIndia ? "INR" : "USD";

//   // Utility: has the stored nextRenewal passed?
//   const isPast = (iso) => {
//     if (!iso) return false;
//     const d = new Date(iso);
//     if (isNaN(d.getTime())) return false;
//     return d.getTime() < Date.now();
//   };

//   // =========================
//   // 1) Probe auth + billing status
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const me = await secureAxios.get("/auth/me"); // non-401
//         const isAuthed = Boolean(me?.data?.authenticated);
//         if (!mounted) return;
//         setAuthed(isAuthed);

//         if (isAuthed) {
//           const s = await secureAxios.get("/billing/status");
//           const t = String(s?.data?.tier || "free").toLowerCase();
//           setTier(t);
//           setManageUrl(s?.data?.manage_url || null);

//           // Server truth (preferred)
//           let serverScheduledPlan = s?.data?.scheduled_plan ? String(s.data.scheduled_plan).toLowerCase() : null;
//           let serverNextRenewal = s?.data?.next_renewal || null;

//           // If server didn't return flags (MVP/older DB), use LS fallback
//           if (!serverScheduledPlan || !serverNextRenewal) {
//             const { plan: lsPlan, next: lsNext, tierAtSchedule } = readLsCancel();

//             // Only trust LS if it matches current paid tier and the date hasn't passed yet
//             const lsLooksValid =
//               lsPlan === "free" &&
//               (t === (tierAtSchedule || t)) &&
//               !!lsNext &&
//               !isPast(lsNext) &&
//               (t === "mini" || t === "pro");

//             if (lsLooksValid) {
//               serverScheduledPlan = "free";
//               serverNextRenewal = lsNext;
//             } else {
//               // LS is stale or mismatched — clear it
//               clearLsCancel();
//             }
//           }

//           if (serverScheduledPlan) setScheduledPlan(serverScheduledPlan);
//           if (serverNextRenewal) setNextRenewal(serverNextRenewal);

//           // If the user is no longer paid or no schedule is active, clear LS
//           if (!(t === "mini" || t === "pro") || !serverScheduledPlan) {
//             clearLsCancel();
//           }

//           localStorage.setItem("tier", t);
//         } else {
//           setTier(null);
//           setManageUrl(null);
//           setScheduledPlan(null);
//           setNextRenewal(null);
//           localStorage.removeItem("tier");
//           clearLsCancel();
//         }
//       } catch {
//         if (!mounted) return;
//         setAuthed(false);
//         setTier(null);
//         setManageUrl(null);
//         setScheduledPlan(null);
//         setNextRenewal(null);
//         clearLsCancel();
//       }
//     })();
//     return () => { mounted = false; };
//   }, []);

//   // =========================
//   // 2) Server prices/currency (canonical)
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const { data } = await secureAxios.get("/billing/prices");
//         if (!mounted) return;
//         if (data?.currency) setServerCurrency(data.currency);
//         if (data?.country) setServerCountry(data.country);
//         setServerPrices({
//           mini_minor: data?.mini_minor ?? 14900,
//           pro_minor: data?.pro_minor ?? 50000,
//           mini_display: data?.mini_display ?? "₹149/mo",
//           pro_display: data?.pro_display ?? "₹500/mo",
//         });
//       } catch {}
//     })();
//     return () => { mounted = false; };
//   }, []);

//   // =========================
//   // 3) VPN guard (optional)
//   // =========================
//   useEffect(() => {
//     let mounted = true;
//     (async () => {
//       try {
//         const { data } = await secureAxios.get("/billing/guard");
//         if (!mounted) return;
//         setVpnInfo({
//           vpn: Boolean(data?.vpn),
//           block: Boolean(data?.block),
//           reason: data?.reason || "ok",
//           country: data?.country || serverCountry,
//           currency: data?.currency || serverCurrency,
//         });
//       } catch {}
//     })();
//     return () => { mounted = false; };
//   }, [serverCountry, serverCurrency]);

//   // =========================
//   // Currency to display (no user toggle; server or fallback)
//   // =========================
//   const displayCurrency = serverCurrency || vpnInfo?.currency || fallbackCurrency;

//   const priceFree = "Free"; // never show $0/₹0
//   const priceMini = serverPrices.mini_display;
//   const pricePro = serverPrices.pro_display;

//   // =========================
//   // Plan cards (content)
//   // =========================
//   const plans = [
//     {
//       id: "free",
//       name: "Free",
//       price: priceFree,
//       model: MODEL_BY_TIER.free,
//       tokens: TOKEN_CAP.free,
//       features: [
//         "20 chats/day",
//         "Session-only search",
//         "Basic OCR",
//         "Uploads: 5 docs/session",
//         "Reference by document name",
//       ],
//     },
//     {
//       id: "mini",
//       name: "Mini+",
//       price: priceMini,
//       model: MODEL_BY_TIER.mini,
//       tokens: TOKEN_CAP.mini,
//       features: [
//         "Unlimited chats (fair use)",
//         "Session-only search",
//         "Faster responses (priority queue)",
//         "Uploads: 20 docs/session",
//         "Basic analytics per chat",
//       ],
//       primary: true,
//     },
//     {
//       id: "pro",
//       name: "Pro",
//       price: pricePro,
//       model: MODEL_BY_TIER.pro,
//       tokens: TOKEN_CAP.pro,
//       features: [
//         "Unlimited chats (fair use)",
//         "Global document search (Pro pool)",
//         "Priority queue (fastest)",
//         "Unlimited uploads + Exports (PDF/JSON/MD)",
//         "Usage analytics dashboard",
//       ],
//     },
//     {
//       id: "enterprise",
//       name: "Enterprise",
//       price: "Custom",
//       model: "Custom",
//       tokens: "Custom",
//       features: ["Multi-seat & Admin controls", "Bulk ingestion & API", "SSO & SLA", "Dedicated support"],
//       enterprise: true,
//     },
//   ];

//   // =========================
//   // CTA logic (per rules)
//   // =========================
//   const isCurrent = (id) => authed && tier && id === tier;
//   const cancellationScheduled = authed && String(scheduledPlan || "").toLowerCase() === "free";

//   const isActionableUpgrade = (planId) => {
//     if (!authed) return false;
//     if (vpnInfo?.block) return false;
//     if (planId === "enterprise") return false;
//     if (tier === "free" && (planId === "mini" || planId === "pro")) return true;
//     if (tier === "mini" && planId === "pro") return true;
//     return false;
//   };

//   const ctaLabel = (plan, loadingPlan) => {
//     if (!authed) return "Login to upgrade";
//     if (plan.enterprise) return "Contact sales";

//     // Current plan:
//     // - Mini+/Pro => "Cancel plan" unless already scheduled (then "Cancellation scheduled")
//     if (isCurrent(plan.id)) {
//       if (cancellationScheduled) return "Cancellation scheduled";
//       if (tier === "mini" || tier === "pro") return "Cancel plan";
//       return "Current plan";
//     }

//     // Upgrades always "Upgrade"
//     if (isActionableUpgrade(plan.id)) {
//       return loadingPlan === plan.id ? "Redirecting…" : "Upgrade";
//     }

//     // Downward / lateral copies
//     if (tier === "pro" && plan.id === "mini") return "Downgrade at renewal";
//     if (tier === "mini" && plan.id === "free") return "Downgrade at renewal";
//     if (tier === "pro" && plan.id === "free") return "Cancel at renewal";
//     return "Get started";
//   };

//   // =========================
//   // Actions
//   // =========================
//   const [loadingPlan, setLoadingPlan] = useState(null);

//   const startCheckout = async (planId) => {
//     try {
//       if (!authed) {
//         navigate("/login");
//         return;
//       }
//       if (vpnInfo?.block) {
//         alert("Billing is disabled while VPN/proxy is detected. Please disable VPN and retry.");
//         return;
//       }
//       if (!isActionableUpgrade(planId)) return;

//       setLoadingPlan(planId);
//       const { data } = await secureAxios.post("/billing/checkout", { plan: planId });
//       if (data?.url) {
//         window.location.href = data.url;
//       } else {
//         alert("Could not start checkout. Please try again.");
//       }
//     } catch (e) {
//       console.error(e);
//       const msg =
//         typeof e?.response?.data?.detail === "object"
//           ? JSON.stringify(e.response.data.detail)
//           : e?.response?.data?.detail || "Checkout failed. Please try again.";
//       alert(msg);
//     } finally {
//       setLoadingPlan(null);
//     }
//   };

//   const cancelPlan = async () => {
//     try {
//       const { data } = await secureAxios.post("/billing/cancel", { mode: "period_end" });

//       // Use response to set flags immediately
//       const sched = data?.scheduled_plan ? String(data.scheduled_plan).toLowerCase() : "free";
//       const next = data?.next_renewal || null;

//       setScheduledPlan(sched);
//       if (next) setNextRenewal(next);
//       setCancelJustScheduled(true);

//       // Persist for refresh if backend doesn't yet return these fields
//       writeLsCancel(sched, next, tier);

//       const niceDate = next ? new Date(next).toLocaleDateString() : "the end of this billing cycle";
//       alert(`Subscription is cancelled and will expire on ${niceDate}.`);
//     } catch {
//       alert("Could not cancel plan. Please try again.");
//     }
//   };

//   const enterpriseClick = () => {
//     window.location.href = "mailto:sales@yourdomain.com?subject=Enterprise%20Plan%20Inquiry";
//   };

//   // =========================
//   // Banners
//   // =========================
//   const BillingUnavailableBanner = () =>
//     vpnInfo?.block ? (
//       <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm">
//         Billing temporarily unavailable while a VPN/proxy is detected. Disable VPN to upgrade.
//       </div>
//     ) : null;

//   const RegionHint = () =>
//     (serverCurrency || vpnInfo?.currency) ? (
//       <div className="mt-2 text-xs text-gray-500">
//         Billing currency: <span className="font-medium">{serverCurrency || vpnInfo?.currency}</span>
//         {serverCountry || vpnInfo?.country ? ` • Region: ${serverCountry || vpnInfo?.country}` : null}
//       </div>
//     ) : null;

//   const ScheduledNote = () =>
//      authed && (cancellationScheduled && nextRenewal) ? (
//        <div className="mt-2 text-xs text-gray-600">
//          Subscription is cancelled and will expire on <b>{formatExpiry(nextRenewal)}</b>.
//        </div>
//      ) : cancelJustScheduled && authed ? (
//        <div className="mt-2 text-xs text-gray-600">
//          Subscription is cancelled and will expire at the end of this billing cycle.
//        </div>
//    ) : null;

//   // ========== Render ==========
//   return (
//     <section className="py-16">
//       <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
//         <div className="flex items-start justify-between">
//           <div>
//             <h1 className="text-3xl font-semibold text-gray-900">Pricing</h1>
//             <p className="mt-2 text-gray-700">Simple plans that scale with your needs.</p>

//             {/* Current plan (only if authenticated) */}
//             {authed && tier && (
//               <div className="mt-3 inline-flex items-center rounded-full border px-4 py-1 text-sm">
//                 Current plan: <span className="ml-2 font-medium uppercase">{tier}</span>
//                 {/* Optional tiny pill here too if you want it on the page header */}
//                 {cancellationScheduled && nextRenewal && (
//                   <span className="ml-3 rounded-full bg-gray-100 border px-2 py-0.5 text-xs text-gray-700">
//                     Cancels on {formatExpiry(nextRenewal)}
//                   </span>
//                 )}
//               </div>
//             )}

//             <RegionHint />
//             <BillingUnavailableBanner />
//             <ScheduledNote />
//           </div>

//           {/* REMOVED page-level Manage button to avoid duplicates.
//               Keep ONLY the global/topbar "Manage plan" near profile/tier. */}
//         </div>

//         {/* Login prompt if logged out */}
//         {!authed && (
//           <div className="mt-4 text-sm text-gray-700">
//             Please{" "}
//             <Link to="/login" className="underline font-medium">
//               log in
//             </Link>{" "}
//             to upgrade.
//           </div>
//         )}

//         <div className="mt-8 grid lg:grid-cols-4 md:grid-cols-2 gap-6">
//           {plans.map((p) => {
//             const isCurrentPlan = isCurrent(p.id);
//             const isEnterprise = p.enterprise;

//             // Allow clicking when:
//             // - Enterprise (contact sales)
//             // - Actionable upgrade (free->mini/pro or mini->pro)
//             // - Current Mini/Pro for Cancel (unless cancellation already scheduled)
//             const allowCancelOnCurrent =
//               authed && !cancellationScheduled && isCurrentPlan && (tier === "mini" || tier === "pro");

//             const canClick =
//               isEnterprise ||
//               isActionableUpgrade(p.id) ||
//               allowCancelOnCurrent;

//             const disabled =
//               vpnInfo?.block || !authed || !canClick;

//             const buttonLabel = isEnterprise
//               ? "Contact sales"
//               : !authed
//               ? "Login to upgrade"
//               : ctaLabel(p, loadingPlan);

//             return (
//               <div
//                 key={p.id}
//                 className={`rounded-2xl border ${p.primary ? "border-indigo-600 shadow-md" : "border-gray-200"} bg-white p-6`}
//               >
//                 <div className={`text-sm font-medium ${p.primary ? "text-indigo-600" : "text-gray-600"}`}>
//                   {p.name}
//                 </div>
//                 <div className="mt-1 text-3xl font-semibold">{p.price}</div>
//                 <div className="mt-2 text-xs text-gray-600">
//                   <div>
//                     <span className="font-medium">Model:</span> {p.model}
//                   </div>
//                   <div>
//                     <span className="font-medium">Monthly token cap:</span>{" "}
//                     {typeof p.tokens === "number" ? p.tokens.toLocaleString() : p.tokens}
//                   </div>
//                 </div>
//                 <ul className="mt-4 space-y-2 text-sm text-gray-700">
//                   {p.features.map((f) => (
//                     <li key={f} className="flex items-center gap-2">
//                       <span className="h-1.5 w-1.5 rounded-full bg-gray-400"></span>
//                       {f}
//                     </li>
//                   ))}
//                 </ul>

//                 {/* CTA */}
//                 {isEnterprise ? (
//                   <button
//                     onClick={enterpriseClick}
//                     className="mt-6 w-full inline-flex justify-center rounded-xl px-4 py-2.5 text-sm font-medium bg-gray-900 text-white hover:bg-black"
//                   >
//                     {buttonLabel}
//                   </button>
//                 ) : (
//                   <>
//                     <button
//                       disabled={disabled}
//                       onClick={() => {
//                         if (isEnterprise) return enterpriseClick();
//                         if (allowCancelOnCurrent) return cancelPlan();
//                         if (isActionableUpgrade(p.id)) return startCheckout(p.id);
//                       }}
//                       className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${
//                         disabled
//                           ? "bg-gray-200 text-gray-500 cursor-not-allowed"
//                           : p.primary
//                           ? "bg-indigo-600 text-white hover:bg-indigo-700"
//                           : "bg-gray-900 text-white hover:bg-black"
//                       }`}
//                       title={
//                         cancellationScheduled && isCurrentPlan
//                           ? `Expires on ${formatExpiry(nextRenewal) || "end of this billing cycle"}`
//                           : vpnInfo?.block
//                           ? "Disable VPN to upgrade"
//                           : !authed
//                           ? "Please log in to upgrade"
//                           : undefined
//                       }
//                     >
//                       {buttonLabel}
//                     </button>

//                     {/* Expiry note right under the button for the current, cancelled plan */}
//                     {isCurrentPlan && cancellationScheduled && (
//                       <div className="mt-2 text-xs text-gray-600">
//                         Expires on <b>{formatExpiry(nextRenewal) || "end of this billing cycle"}</b>.
//                       </div>
//                     )}
//                   </>
//                 )}
//               </div>
//             );
//           })}
//         </div>

//         <div className="mt-10 text-sm text-gray-600">
//           <h3 className="font-medium text-gray-900">FAQs</h3>
//           <p className="mt-2">
//             • Upgrades are immediate and charged in full today. Your billing cycle resets to today → +1 month.
//           </p>
//           <p className="mt-2">
//             • Downgrades/cancellations take effect at the next renewal. You keep current plan perks until then.
//           </p>
//           <p className="mt-2">• Token caps shown are fair-use guardrails; enforcement is server-side.</p>
//           <p className="mt-2">• Prices use your region’s billing currency; final price is confirmed during checkout.</p>
//         </div>
//       </div>
//     </section>
//   );
// }
