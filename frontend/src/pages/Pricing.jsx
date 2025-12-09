import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import secureAxios from "../utils/secureAxios";
import { motion } from "framer-motion";
import { Check, Sparkles, Stars, Cpu, Globe, GaugeCircle } from "lucide-react";

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
// Constants (visual only; server is canonical for pricing)
// ------------------------------
const TOKEN_CAP = { base: 500_000, pro: 1_500_000 };
const MODEL_BY_TIER = { base: "gpt-4o-mini", pro: "gpt-5" };

// localStorage helpers (keep: cancel-at-period-end banner UX)
const LS_KEYS = {
  plan: "cancel_scheduled_plan",
  next: "cancel_next_renewal_iso",
  tierAtSchedule: "cancel_scheduled_tier",
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

// Helpers
const formatExpiry = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString() : n);

const TinyBadge = ({ children, className = "" }) => (
  <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{children}</span>
);
const Feature = ({ children }) => (
  <li className="flex items-center gap-2 text-sm text-gray-700"><Check className="h-4 w-4" />{children}</li>
);
// src/components/PricingSection.jsx
export default function PricingSection() {
  return (
    <section id="pricing" className="max-w-5xl mx-auto px-6 py-16">
      <div className="text-center mb-10">
        <h2 className="text-3xl font-semibold mb-2">Pricing</h2>
        <p className="text-slate-600">
          One simple plan for solo consultants, and custom plans for teams.
          Billed in USD. No per-document fees.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Pro – launch offer */}
        <div className="border border-indigo-500 rounded-2xl p-6 shadow-lg relative bg-white">
          <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs px-3 py-1 rounded-full bg-indigo-500 text-white">
            Launch offer
          </span>

          <h3 className="text-lg font-semibold mb-1">Pro</h3>

          {/* Price + anchor */}
          <div className="mb-1 flex items-baseline gap-2">
            <span className="text-3xl font-semibold">$25</span>
            <span className="text-sm text-slate-500">/ month</span>
          </div>

          <p className="text-xs text-slate-500 mb-3">
            <span className="line-through text-slate-400 mr-1">$75</span>
            <span className="font-medium text-emerald-600">
              Early adopter pricing
            </span>
            {" – lock in $25/mo for as long as your subscription stays active."}
          </p>

          <p className="text-sm text-slate-600 mb-4">
            Best for solo ECM / OpenText consultants doing day-to-day client work.
          </p>

          <ul className="text-sm text-slate-700 space-y-2 mb-6">
            {/* <li>• Global doc search across all uploads</li> */}
            <li>• OCR on PDFs & images</li>
            <li>• Unlimited projects & chat history</li>
            {/* <li>• Chat export (.md / .txt)</li> */}
            <li>• Priority email support</li>
          </ul>

          <button className="w-full rounded-xl bg-indigo-600 text-white py-2 text-sm font-medium hover:bg-indigo-700">
            Start Pro for $25
          </button>

          <p className="text-xs text-slate-500 mt-3">
            Billed in USD worldwide. Standard price for new users will be
            $75/month in a future release. Cancel anytime.
          </p>
        </div>

        {/* Teams / Enterprise */}
        <div className="border border-slate-200 rounded-2xl p-6">
          <h3 className="text-lg font-semibold mb-1">Teams &amp; Enterprise</h3>
          <p className="text-2xl font-semibold mb-4">Custom</p>
          <p className="text-sm text-slate-600 mb-4">
            For consulting firms and in-house ECM teams needing shared workspaces,
            higher limits, and SSO.
          </p>
          <a
            href="mailto:support@neurokron.com"
            className="block w-full text-center rounded-xl border border-slate-300 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Contact us
          </a>
        </div>
      </div>

      <div className="mt-8 text-xs text-slate-500 text-center space-y-1">
        <p>All plans are billed in USD. One subscription per user.</p>
        <p>Your documents and chats are not used to train our models.</p>
      </div>
    </section>
  );
}

// export default function Pricing() {
//   const navigate = useNavigate();

//   // --- Auth & plan state ---
//   const [authed, setAuthed] = useState(false);
//   const [tier, setTier] = useState(null); // 'base' | 'pro' | null
//   const [trialActive, setTrialActive] = useState(false);
//   const [manageUrl, setManageUrl] = useState(null);

//   // Cancellation scheduling info
//   const [scheduledPlan, setScheduledPlan] = useState(null); // e.g. 'free'
//   const [nextRenewal, setNextRenewal] = useState(null);     // ISO string
//   const [cancelJustScheduled, setCancelJustScheduled] = useState(false);

//   // --- Canonical prices/currency/region from server ---
//   const [serverCurrency, setServerCurrency] = useState(null); // 'INR' | 'USD'
//   const [serverCountry, setServerCountry] = useState(null);   // e.g. 'IN'
//   const [serverPrices, setServerPrices] = useState({
//     base_minor: 14900,
//     pro_minor: 50000,
//     base_display: "₹149/mo",
//     pro_display: "₹500/mo",
//   });

//   // --- VPN guard (optional; fail-open) ---
//   const [vpnInfo, setVpnInfo] = useState({ vpn: false, block: false, reason: "ok", country: null, currency: null });

//   const initialIsIndia = useMemo(() => DETECT_IS_INDIA(), []);
//   const fallbackCurrency = initialIsIndia ? "INR" : "USD";

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
//         const me = await secureAxios.get("/auth/me");
//         const isAuthed = Boolean(me?.data?.authenticated);
//         if (!mounted) return;
//         setAuthed(isAuthed);

//         if (isAuthed) {
//           const s = await secureAxios.get("/billing/status");
//           // backend returns: tier, pro_trial_active
//           const tRaw = (s?.data?.tier || "base").toString().toLowerCase();
//           // legacy 'mini' → 'base'
//           const t = tRaw === "mini" ? "base" : tRaw;
//           setTier(t);
//           setTrialActive(Boolean(s?.data?.pro_trial_active));
//           setManageUrl(s?.data?.manage_url || null);

//           // cancel flags
//           let serverScheduledPlan = s?.data?.scheduled_plan ? String(s.data.scheduled_plan).toLowerCase() : null;
//           let serverNextRenewal = s?.data?.next_renewal || null;

//           if (!serverScheduledPlan || !serverNextRenewal) {
//             const { plan: lsPlan, next: lsNext, tierAtSchedule } = readLsCancel();
//             const lsLooksValid =
//               lsPlan === "free" && (t === (tierAtSchedule || t)) && !!lsNext && !isPast(lsNext) && (t === "base" || t === "pro");
//             if (lsLooksValid) {
//               serverScheduledPlan = "free";
//               serverNextRenewal = lsNext;
//             } else {
//               clearLsCancel();
//             }
//           }

//           if (serverScheduledPlan) setScheduledPlan(serverScheduledPlan);
//           if (serverNextRenewal) setNextRenewal(serverNextRenewal);
//           if (!(t === "base" || t === "pro") || !serverScheduledPlan) {
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
//           base_minor: data?.base_minor ?? data?.mini_minor ?? 14900,
//           pro_minor: data?.pro_minor ?? 50000,
//           base_display: data?.base_display ?? data?.mini_display ?? "₹149/mo",
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
//   // Currency to display
//   // =========================
//   const displayCurrency = serverCurrency || vpnInfo?.currency || fallbackCurrency;
//   const priceBase = serverPrices.base_display;
//   const pricePro  = serverPrices.pro_display;

//   // =========================
//   // Plan cards (content)
//   // =========================
//   const plans = [
//     {
//       id: "base",
//       name: "Base",
//       blurb: "Unlimited document summarization.",
//       price: priceBase,
//       model: MODEL_BY_TIER.base,
//       tokens: TOKEN_CAP.base,
//       icon: GaugeCircle,
//       features: [
//         "Unlimited summarize (fair use)",
//         "Session-only search",
//         "Fast responses (4o Mini/4o)",
//         "Uploads: 20 docs/session",
//       ],
//       primary: true,
//     },
//     {
//       id: "pro",
//       name: "Pro",
//       blurb: "Full Q&A + global search + exports.",
//       price: pricePro,
//       model: MODEL_BY_TIER.pro,
//       tokens: TOKEN_CAP.pro,
//       icon: Cpu,
//       features: [
//         "Q&A over global document pool",
//         "GPT-5 with smart query refinement",
//         "Exports & analytics",
//         "Priority queue",
//       ],
//     },
//     {
//       id: "enterprise",
//       name: "Enterprise",
//       blurb: "Scale with SSO, SLAs and support.",
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
//   // CTA logic
//   // =========================
//   const isCurrent = (id) => authed && tier && id === tier;
//   const cancellationScheduled = authed && String(scheduledPlan || "").toLowerCase() === "free";

//   const isActionableUpgrade = (planId) => {
//     if (!authed) return false;
//     if (vpnInfo?.block) return false;
//     if (planId === "enterprise") return false;
//     if (tier === "base" && planId === "pro") return true;
//     if (!tier && (planId === "base" || planId === "pro")) return true;
//     return false;
//   };

//   const ctaLabel = (plan, loadingPlan) => {
//     if (!authed) return "Login to upgrade";
//     if (plan.enterprise) return "Contact sales";
//     if (isCurrent(plan.id)) {
//       if (cancellationScheduled) return "Cancellation scheduled";
//       if (tier === "base" || tier === "pro") return "Cancel plan";
//       return "Current plan";
//     }
//     if (isActionableUpgrade(plan.id)) return loadingPlan === plan.id ? "Redirecting…" : "Upgrade";
//     if (tier === "pro" && plan.id === "base") return "Downgrade at renewal";
//     return "Get started";
//   };

//   // =========================
//   // Actions
//   // =========================
//   const [loadingPlan, setLoadingPlan] = useState(null);
//   const [startingTrial, setStartingTrial] = useState(false);

//   const startCheckout = async (planId) => {
//     try {
//       if (!authed) { navigate("/login"); return; }
//       if (vpnInfo?.block) { alert("Billing is disabled while a VPN/proxy is detected. Please disable VPN and retry."); return; }
//       if (!isActionableUpgrade(planId)) return;

//       setLoadingPlan(planId);
//       const { data } = await secureAxios.post("/billing/checkout", { plan: planId }); // plan: 'base' | 'pro'
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

//   const startTrial = async () => {
//     try {
//       if (!authed) { navigate("/login"); return; }
//       setStartingTrial(true);
//       await secureAxios.post("/billing/trial/start"); // backend enables pro trial immediately
//       setTrialActive(true);
//       setTier("pro"); // unlock UI instantly during trial
//       alert("Your 7-day Pro trial is active!");
//     } catch (e) {
//       const msg = e?.response?.data?.detail || e?.message || "Could not start trial.";
//       alert(msg);
//     } finally {
//       setStartingTrial(false);
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
//   // Banners / Hints
//   // =========================
//   const BillingUnavailableBanner = () => (
//     vpnInfo?.block ? (
//       <div className="rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm">
//         Billing is unavailable while a VPN/proxy is detected. Please turn it off to upgrade.
//       </div>
//     ) : null
//   );

//   const RegionHint = () => (
//     (serverCurrency || vpnInfo?.currency) ? (
//       <div className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs text-gray-600">
//         Billed in <span className="font-medium">{serverCurrency || vpnInfo?.currency}</span>
//         {(serverCountry || vpnInfo?.country) && <span>• {serverCountry || vpnInfo?.country}</span>}
//       </div>
//     ) : null
//   );

//   const ScheduledNote = () => (
//     authed && (cancellationScheduled && nextRenewal) ? (
//       <div className="text-xs text-gray-600">
//         Subscription is cancelled and will expire on <b>{formatExpiry(nextRenewal)}</b>.
//       </div>
//     ) : cancelJustScheduled && authed ? (
//       <div className="text-xs text-gray-600">
//         Subscription is cancelled and will expire at the end of this billing cycle.
//       </div>
//     ) : null
//   );

//   // =========================
//   // Plan Card
//   // =========================
//   const PlanCard = ({ p }) => {
//     const isEnterprise = p.enterprise;
//     const isCurrentPlan = isCurrent(p.id);
//     const allowCancelOnCurrent = authed && !cancellationScheduled && isCurrentPlan && (tier === "base" || tier === "pro");
//     const canClick = isEnterprise || isActionableUpgrade(p.id) || allowCancelOnCurrent;
//     const disabled = vpnInfo?.block || !authed || !canClick;
//     const buttonLabel = isEnterprise ? "Contact sales" : (!authed ? "Login to upgrade" : ctaLabel(p, loadingPlan));
//     const Icon = p.icon || Stars;

//     const showTrialCta = p.id === "pro" && authed && !trialActive && tier !== "pro";

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
//           {!isEnterprise && <span className="text-xs text-gray-500">/month</span>}
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
//           <button
//             onClick={enterpriseClick}
//             className="mt-6 w-full inline-flex justify-center rounded-xl px-4 py-2.5 text-sm font-medium bg-gray-900 text-white hover:bg-black"
//           >
//             {buttonLabel}
//           </button>
//         ) : (
//           <>
//             {/* Pro trial CTA when eligible */}
//             {showTrialCta && (
//               <button
//                 onClick={startTrial}
//                 disabled={startingTrial}
//                 className="mt-6 w-full rounded-xl bg-indigo-600 text-white px-4 py-2.5 text-sm font-medium hover:bg-indigo-700"
//               >
//                 {startingTrial ? "Starting trial…" : "Start 7-day free trial"}
//               </button>
//             )}

//             <button
//               disabled={disabled}
//               onClick={() => {
//                 if (isEnterprise) return enterpriseClick();
//                 if (allowCancelOnCurrent) return cancelPlan();
//                 if (isActionableUpgrade(p.id)) return startCheckout(p.id);
//               }}
//               className={`mt-3 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${
//                 disabled
//                   ? "bg-gray-200 text-gray-500 cursor-not-allowed"
//                   : p.primary
//                   ? "bg-gray-900 text-white hover:bg-black"
//                   : "bg-gray-900 text-white hover:bg-black"
//               }`}
//               title={
//                 cancellationScheduled && isCurrentPlan
//                   ? `Expires on ${formatExpiry(nextRenewal) || "end of this billing cycle"}`
//                   : vpnInfo?.block
//                   ? "Disable VPN to upgrade"
//                   : !authed
//                   ? "Please log in to upgrade"
//                   : undefined
//               }
//             >
//               {buttonLabel}
//             </button>

//             {isCurrentPlan && cancellationScheduled && (
//               <div className="mt-2 text-xs text-gray-600">
//                 Expires on <b>{formatExpiry(nextRenewal) || "end of this billing cycle"}</b>.
//               </div>
//             )}
//           </>
//         )}
//       </motion.div>
//     );
//   };

//   return (
//     <section className="relative">
//       <div
//         aria-hidden
//         className="pointer-events-none absolute inset-x-0 -top-20 -z-10 h-64 bg-gradient-to-b from-indigo-50 via-white to-white"
//       />

//       <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14">
//         {/* BOXED HERO PANEL */}
//         <div className="rounded-3xl border border-gray-200 bg-white/70 backdrop-blur p-6 md:p-8 shadow-sm">
//           <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
//             {/* LEFT */}
//             <div className="max-w-3xl">
//               <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
//                 <Stars className="h-3.5 w-3.5" /> Fair, flexible pricing
//               </div>

//               <h1 className="mt-3 text-4xl md:text-5xl lg:text-6xl font-semibold text-gray-900 tracking-tight leading-tight">
//                 Plans
//               </h1>
//               <p className="mt-3 text-base md:text-lg text-gray-700 leading-relaxed [text-wrap:balance]">
//                 Pick a plan that fits your workload. Clear limits, no surprises.
//               </p>
//             </div>

//             {/* RIGHT */}
//             <div className="w-full md:w-auto md:min-w-[320px] flex flex-col items-start md:items-end gap-2">
//               {/* Current plan chip */}
//               {authed && tier && (
//                 <div className="inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm bg-white">
//                   <span className="text-gray-600">Current plan:</span>
//                   <span className="font-medium uppercase">{trialActive ? "PRO (TRIAL)" : tier}</span>
//                   {cancellationScheduled && nextRenewal && (
//                     <span className="ml-1 rounded-full bg-gray-100 border px-2 py-0.5 text-xs text-gray-700">
//                       Ends on {formatExpiry(nextRenewal)}
//                     </span>
//                   )}
//                 </div>
//               )}

//               {/* Region chip */}
//               <RegionHint />

//               {/* Manage / Login chip */}
//               {authed && manageUrl ? (
//                 <a
//                   href={manageUrl}
//                   className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
//                 >
//                   Manage plan
//                 </a>
//               ) : !authed ? (
//                 <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700">
//                   Please{" "}
//                   <Link to="/login" className="underline font-medium">
//                     log in
//                   </Link>{" "}
//                   to upgrade.
//                 </div>
//               ) : null}

//               {/* Notes */}
//               <ScheduledNote />
//               <div className="w-full md:w-auto">
//                 <BillingUnavailableBanner />
//               </div>
//             </div>
//           </div>
//         </div>

//         <motion.div layout className="mt-10 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
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
