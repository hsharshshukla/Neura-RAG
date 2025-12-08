# app/routes/billing.py
from __future__ import annotations

import os, json, hmac, hashlib, logging
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session, select
from sqlalchemy import select as sa_select, text

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user
from app.rate_limit import key_user_or_ip  # SlowAPI per-endpoint limiter

# -------------------- Plan constants / helpers --------------------
# We normalize storage to only: "free" | "pro"
try:
    from app.config.plan_policy import PLAN_FREE, PLAN_MINI, PLAN_PRO
except Exception:
    PLAN_FREE = "free"
    PLAN_MINI = "mini"
    PLAN_PRO  = "pro"

# Optional import for usage-aware refunds (best-effort)
try:
    from app.config.plan_policy import monthly_usage_percent as _monthly_usage_percent
except Exception:
    _monthly_usage_percent = None  # fallback below

def _canon_plan_for_storage(plan_str: str) -> str:
    """
    Map UI/checkout plan names to canonical DB tier.
    We store only "free" or "pro".
    """
    p = (plan_str or "").strip().lower()
    if p in {"pro"}:
        return PLAN_PRO
    # Treat "base" and "mini" as free-tier in storage.
    return PLAN_FREE

def _is_pro(user: User) -> bool:
    return (getattr(user, "tier", "") or "").lower() == PLAN_PRO

# -------------------- Email notifications (best-effort) --------------------
from app.email.events import (
    send_subscription_activated,
    send_payment_failed,
    send_cancellation_confirmed,
    send_refund_issued,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

# -------------------- local time helper & trial config --------------------
def _now_utc() -> datetime:
    # naive UTC; DB columns are TIMESTAMP WITHOUT TIME ZONE
    return datetime.utcnow()

PRO_TRIAL_DAYS = int(os.getenv("PRO_TRIAL_DAYS", "7"))

# -------------------- env & pricing helpers --------------------
# Provider: "dummy" (dev) or "razorpay" (prod)
GATEWAY = os.getenv("PAYMENT_GATEWAY", "dummy").lower()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:3000")

# Prices in minor units (paise/cents)
PRICE_BASE_INR = int(os.getenv("PRICE_BASE_INR", "15000"))   # ₹150.00
PRICE_PRO_INR  = int(os.getenv("PRICE_PRO_INR",  "50000"))   # ₹500.00
PRICE_BASE_USD = int(os.getenv("PRICE_BASE_USD", "300"))     # $3.00
PRICE_PRO_USD  = int(os.getenv("PRICE_PRO_USD",  "1500"))    # $15.00

# Refund / cancellation policy
REFUND_WINDOW_DAYS       = int(os.getenv("REFUND_WINDOW_DAYS", "2"))
REFUND_USAGE_MAX_PERCENT = float(os.getenv("REFUND_USAGE_MAX_PERCENT", "20"))
BILLING_RETRY_GRACE_DAYS = int(os.getenv("BILLING_RETRY_GRACE_DAYS", "7"))

# Razorpay credentials (when PAYMENT_GATEWAY=razorpay)
RZP_KEY_ID         = os.getenv("RZP_KEY_ID", "")
RZP_KEY_SECRET     = os.getenv("RZP_KEY_SECRET", "")
RZP_WEBHOOK_SECRET = os.getenv("RZP_WEBHOOK_SECRET", "")

# VPN guard knobs
VPN_BLOCK_ENABLED      = (os.getenv("VPN_BLOCK_ENABLED", "true").lower() in ("1","true","yes"))
VPN_HEADER_NAME        = os.getenv("VPN_HEADER_NAME", "X-VPN-Detected")
VPN_TRUE_VALUES        = {v.strip().lower() for v in os.getenv("VPN_TRUE_VALUES", "1,true,yes").split(",")}
DEV_FORCE_VPN          = (os.getenv("DEV_FORCE_VPN", "false").lower() in ("1","true","yes"))
DEV_FORCE_COUNTRY      = (os.getenv("DEV_FORCE_COUNTRY") or "").upper().strip()

# -------------------- geo / currency --------------------
def _detect_country(request: Request, user: Optional[User] = None) -> str:
    if DEV_FORCE_COUNTRY:
        return DEV_FORCE_COUNTRY

    # Prefer edge header (Cloudflare etc)
    for h in ("CF-IPCountry", "X-Country-Code", "X-Geo-Country"):
        v = request.headers.get(h)
        if v:
            return v.upper()

    # Fallback to stored user country
    if user is not None:
        c = (getattr(user, "country", None) or "").upper()
        if c:
            return c

    # Weak Accept-Language inference; default India
    al = request.headers.get("Accept-Language", "")
    if "-IN" in al.upper():
        return "IN"

    return "IN"

def _currency_for_country(cc: str) -> str:
    return "INR" if cc == "IN" else "USD"

def _prices_for_currency(curr: str) -> dict:
    if curr == "INR":
        return {
            "base_minor": PRICE_BASE_INR,
            "pro_minor":  PRICE_PRO_INR,
            "base_display": f"₹{PRICE_BASE_INR // 100}/mo",
            "pro_display":  f"₹{PRICE_PRO_INR // 100}/mo",
        }
    def fmt(n: int) -> str:
        return f"${(n/100):.0f}/mo" if n % 100 == 0 else f"${n/100:.2f}/mo"
    return {
        "base_minor": PRICE_BASE_USD,
        "pro_minor":  PRICE_PRO_USD,
        "base_display": fmt(PRICE_BASE_USD),
        "pro_display":  fmt(PRICE_PRO_USD),
    }

def _vpn_detected(request: Request) -> bool:
    if DEV_FORCE_VPN:
        return True
    header_val = (request.headers.get(VPN_HEADER_NAME) or "").strip().lower()
    return bool(header_val) and (header_val in VPN_TRUE_VALUES)

# -------------------- Razorpay provider --------------------
async def _rzp_create_payment_link(user: User, ui_plan: str, currency: str, amount_minor: int) -> str:
    """
    ui_plan is "base" or "pro" for display; we still store canonical tier in DB after webhook.
    """
    payload = {
        "amount": amount_minor,
        "currency": currency,
        "accept_partial": False,
        "reference_id": f"user_{user.id}_{ui_plan}_{int(_now_utc().timestamp())}",
        "description": f"{ui_plan.capitalize()} plan",
        "customer": {"name": user.name or user.email.split('@')[0], "email": user.email},
        "notify": {"email": True, "sms": False},
        "callback_url": f"{APP_BASE_URL}/billing/success",
        "callback_method": "get",
        "notes": {"user_id": str(user.id), "plan": ui_plan},
    }
    auth = (RZP_KEY_ID, RZP_KEY_SECRET)
    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        r = await client.post("https://api.razorpay.com/v1/payment_links", json=payload)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail={"provider": "razorpay", "error": r.text})
    data = r.json()
    short_url = data.get("short_url")
    if not short_url:
        raise HTTPException(status_code=502, detail={"provider": "razorpay", "error": "missing short_url"})
    return short_url

def _rzp_verify(signature_header: str, raw_body: bytes) -> bool:
    mac = hmac.new(RZP_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature_header or "")

def _rzp_extract(evt: Dict[str, Any]) -> dict:
    """
    Extract minimal fields across payment_link/order/payment events.
    """
    out = {"event": evt.get("event")}
    p = evt.get("payload", {}) or {}
    if "payment_link" in p:
        ent = (p["payment_link"].get("entity") or {})
        notes = ent.get("notes") or {}
        out["user_id"] = int(notes.get("user_id")) if str(notes.get("user_id") or "").isdigit() else None
        out["plan"] = (notes.get("plan") or "").lower() or None
        out["status"] = ent.get("status")
        payments = ent.get("payments", [])
        if payments and isinstance(payments, list):
            out["payment_id"] = payments[0].get("id")
    if "order" in p and not out.get("user_id"):
        ent = (p["order"].get("entity") or {})
        notes = ent.get("notes") or {}
        out["user_id"] = int(notes.get("user_id")) if str(notes.get("user_id") or "").isdigit() else None
        out["plan"] = (notes.get("plan") or "").lower() or None
        out["status"] = ent.get("status")
    if "payment" in p:
        ent = (p["payment"].get("entity") or {})
        out["payment_id"] = out.get("payment_id") or ent.get("id")
        notes = ent.get("notes") or {}
        if not out.get("user_id"):
            out["user_id"] = int(notes.get("user_id")) if str(notes.get("user_id") or "").isdigit() else None
        if not out.get("plan"):
            out["plan"] = (notes.get("plan") or "").lower() or None
        out["status"] = out.get("status") or ent.get("status")
    return out

async def _rzp_refund(payment_id: str, amount_minor: Optional[int] = None) -> dict:
    if not payment_id:
        raise HTTPException(status_code=400, detail="Missing payment_id for refund")
    payload: Dict[str, Any] = {}
    if amount_minor:
        payload["amount"] = amount_minor
    auth = (RZP_KEY_ID, RZP_KEY_SECRET)
    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        r = await client.post(f"https://api.razorpay.com/v1/payments/{payment_id}/refund", json=payload)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Razorpay refund error: {r.text}")
    return r.json()

# -------------------- helpers --------------------
def _set_payment_meta_safe(user: User, payment_id: Optional[str]) -> None:
    try:
        if hasattr(user, "last_payment_at"):
            setattr(user, "last_payment_at", _now_utc())
    except Exception:
        pass
    try:
        if hasattr(user, "last_payment_id") and payment_id:
            setattr(user, "last_payment_id", payment_id)
    except Exception:
        pass

def _calc_next_renewal(user: User) -> datetime:
    try:
        last_paid_at: datetime | None = getattr(user, "last_payment_at", None)
    except Exception:
        last_paid_at = None
    if isinstance(last_paid_at, datetime):
        return last_paid_at + timedelta(days=30)
    try:
        existing: datetime | None = getattr(user, "next_renewal_at", None)
        if isinstance(existing, datetime):
            return existing
    except Exception:
        pass
    return _now_utc() + timedelta(days=30)

def _set_cancel_flags_safe(user: User, enabled: bool, next_renewal: Optional[datetime]) -> None:
    for name, val in (
        ("cancel_at_period_end", enabled),
        ("scheduled_plan", PLAN_FREE if enabled else None),
        ("next_renewal_at", next_renewal if enabled else None),
    ):
        try:
            if hasattr(user, name):
                setattr(user, name, val)
        except Exception:
            pass

def _ensure_billing_tables(db: Session) -> None:
    # Persist webhook events idempotently
    db.exec(text("""
        CREATE TABLE IF NOT EXISTS public.billing_event (
            id BIGSERIAL PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT,
            provider TEXT,
            user_id INTEGER,
            payload JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
    """))
    db.commit()

def _is_trusted_webhook(req: Request) -> bool:
    if GATEWAY == "razorpay":
        return bool(req.headers.get("X-Razorpay-Signature"))
    return bool(req.headers.get("X-Signature"))

def _webhook_event_id(raw: bytes, info: Dict[str, Any]) -> str:
    pid = (info.get("payment_id") or "").strip()
    if pid:
        return f"rzp:{pid}"
    return hashlib.sha256(raw).hexdigest()

# -------------------- routes --------------------
@router.get("/guard")
# @limiter.limit("120/minute")
def vpn_guard(request: Request, response: Response):
    cc = _detect_country(request)
    cur = _currency_for_country(cc)
    vpn = _vpn_detected(request)
    block = vpn and VPN_BLOCK_ENABLED
    return {
        "vpn": vpn,
        "block": block,
        "reason": "vpn_detected" if block else "ok",
        "country": cc,
        "currency": cur,
    }

@router.get("/prices")
# @limiter.limit("60/minute")
def get_prices(request: Request, response: Response):
    cc = _detect_country(request)
    currency = _currency_for_country(cc)
    p = _prices_for_currency(currency)
    return {"currency": currency, "country": cc, **p}

@router.get("/status")
# @limiter.limit("60/minute")
def billing_status(
    request: Request,
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    scheduled_plan = getattr(user, "scheduled_plan", None)
    next_renewal_dt = getattr(user, "next_renewal_at", None)
    cancel_flag = bool(getattr(user, "cancel_at_period_end", False))

    resp = {
        # Always report canonical storage tier ("free" or "pro")
        "tier": (user.tier or PLAN_FREE),
        "manage_url": None,
        "scheduled_plan": scheduled_plan,
        "next_renewal": next_renewal_dt.isoformat() if isinstance(next_renewal_dt, datetime) else None,
        "cancel_at_period_end": cancel_flag,
        # trial flag (true if a trial exists and hasn't been cancelled)
        "pro_trial_active": bool(getattr(user, "pro_trial_started_at", None)) and not bool(getattr(user, "pro_trial_cancelled", False)),
    }
    if request is not None:
        cc = _detect_country(request, user)
        resp["currency"] = _currency_for_country(cc)
        resp["country"] = cc
        resp["vpn_blocked"] = (_vpn_detected(request) and VPN_BLOCK_ENABLED)
    return resp

@router.post("/checkout")
# @limiter.limit("6/minute; 60/hour")
async def start_checkout(
    body: Dict[str, Any],
    request: Request,
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    body = { "plan": "base" | "pro" }
    - UI sends "base" or "pro".
    - We always store "free" or "pro" on the user record.
    """
    if _vpn_detected(request) and VPN_BLOCK_ENABLED:
        raise HTTPException(status_code=403, detail="Billing disabled while VPN/proxy is detected. Please disable VPN and retry.")

    ui_plan = (body.get("plan") or "").lower().strip()
    if ui_plan not in {"base", "pro"}:
        raise HTTPException(status_code=400, detail="Plan must be 'base' or 'pro'")

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    cc = _detect_country(request, user)
    currency = _currency_for_country(cc)
    prices = _prices_for_currency(currency)
    amount_minor = prices["base_minor"] if ui_plan == "base" else prices["pro_minor"]

    # If user is on a trial and buys Pro, convert to paid immediately
    if getattr(user, "pro_trial_started_at", None) and ui_plan == "pro":
        setattr(user, "pro_trial_cancelled", True)

    if GATEWAY == "razorpay":
        url = await _rzp_create_payment_link(user, ui_plan, currency, amount_minor)
        return {"url": url}

    # Dummy provider: flip the tier immediately
    if GATEWAY == "dummy":
        user.tier = _canon_plan_for_storage(ui_plan)
        setattr(user, "is_pro_paid_active", _is_pro(user))
        _set_payment_meta_safe(user, f"dummy_{int(_now_utc().timestamp())}")
        try:
            if hasattr(user, "next_renewal_at"):
                setattr(user, "next_renewal_at", _now_utc() + timedelta(days=30))
        except Exception:
            pass
        _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
        db.add(user); db.commit()

        try:
            await send_subscription_activated(user.email, user.tier)
        except Exception as e:
            log.exception("send_subscription_activated failed (dummy checkout) for %s: %s", user.email, e)

        url = f"{APP_BASE_URL}/billing/success?plan={ui_plan}&user={user.id}&currency={currency}&amount={amount_minor}"
        return {"url": url}

    raise HTTPException(status_code=501, detail=f"Provider {GATEWAY} not implemented")

@router.post("/trial/start")
# @limiter.limit("6/minute; 60/hour", key_func=key_user_or_ip)
async def start_pro_trial(
    request: Request,
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # already paid Pro
    if getattr(user, "is_pro_paid_active", False) or _is_pro(user):
        raise HTTPException(status_code=400, detail="You already have Pro.")

    # already have an active trial
    if getattr(user, "pro_trial_started_at", None) and not getattr(user, "pro_trial_cancelled", False):
        raise HTTPException(status_code=400, detail="Pro trial already active.")

    setattr(user, "pro_trial_started_at", _now_utc())
    setattr(user, "pro_trial_cancelled", False)

    # OPTIONAL: lift UI plan during trial (keeps experience consistent)
    user.tier = PLAN_PRO
    db.add(user); db.commit()

    trial_ends_at = getattr(user, "pro_trial_started_at") + timedelta(days=PRO_TRIAL_DAYS)
    return {"ok": True, "trial_ends_at": trial_ends_at.isoformat()}

@router.post("/trial/cancel")
# @limiter.limit("6/minute; 60/hour", key_func=key_user_or_ip)
async def cancel_pro_trial(
    request: Request,
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not getattr(user, "pro_trial_started_at", None):
        raise HTTPException(status_code=400, detail="No trial to cancel.")

    setattr(user, "pro_trial_cancelled", True)
    # Keep tier as-is; you can run a scheduler to flip to free at trial end if desired
    db.add(user); db.commit()
    return {"ok": True}

@router.post("/webhook")
# @limiter.limit("30/minute", exempt_when=_is_trusted_webhook)
async def handle_webhook(
    request: Request,
    response: Response,
    db: Session = Depends(get_session)
):
    raw = await request.body()

    # Verify + parse provider payload
    if GATEWAY == "razorpay":
        sig = request.headers.get("X-Razorpay-Signature", "")
        if not sig or not _rzp_verify(sig, raw):
            raise HTTPException(status_code=400, detail="Invalid Razorpay signature")
        evt = json.loads(raw.decode("utf-8"))
        info = _rzp_extract(evt)
    else:
        evt = json.loads(raw.decode("utf-8"))
        info = {
            "event": evt.get("event", "dummy"),
            "user_id": evt.get("user_id"),
            "plan": (evt.get("plan") or "").lower() or None,
            "payment_id": evt.get("payment_id"),
            "status": evt.get("status"),
        }

    # Ensure idempotency infra
    _ensure_billing_tables(db)
    event_id = _webhook_event_id(raw, info)
    event_type = (info.get("event") or "").lower()
    provider = GATEWAY

    already = db.exec(text("SELECT 1 FROM public.billing_event WHERE event_id = :e").bindparams(e=event_id)).first()
    if already:
        return {"status": "ok", "idempotent": True}

    user_id = info.get("user_id")
    ui_plan = info.get("plan")  # may be "base" or "pro"
    payment_id = info.get("payment_id")

    # Always store the raw event for debugging
    to_store = {"event": event_type, "info": info, "provider": provider}

    if not user_id:
        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=None, j=json.dumps(to_store)))
        db.commit()
        return {"status": "ignored", "reason": "no user_id", "event": event_type}

    is_paid = False
    if GATEWAY == "razorpay":
        is_paid = event_type in {"payment_link.paid", "order.paid", "payment.captured"}

    if not (is_paid and ui_plan in {"base", "pro"}):
        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps(to_store)))
        db.commit()
        return {"status": "ignored", "event": event_type}

    # Canonical storage tier
    canonical = _canon_plan_for_storage(ui_plan)

    try:
        with db.begin():
            locked_stmt = sa_select(User).where(User.id == user_id).with_for_update()
            user = db.exec(locked_stmt).first()
            if not user:
                db.exec(text("""
                    INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
                    VALUES (:i, :t, :p, :u, :j)
                """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps({**to_store, "err": "user_missing"})))
                db.commit()
                return {"status": "ignored", "reason": "user missing", "event": event_type}

            # Apply plan
            user.tier = canonical  # "free" or "pro"
            setattr(user, "is_pro_paid_active", canonical == PLAN_PRO)
            _set_payment_meta_safe(user, payment_id)
            try:
                if hasattr(user, "next_renewal_at"):
                    setattr(user, "next_renewal_at", _now_utc() + timedelta(days=30))
            except Exception:
                pass
            _set_cancel_flags_safe(user, enabled=False, next_renewal=None)

            # If they had a trial, mark it cancelled since they paid
            if getattr(user, "pro_trial_started_at", None):
                setattr(user, "pro_trial_cancelled", True)

            db.add(user)

        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps(to_store)))
        db.commit()

        try:
            await send_subscription_activated(user.email, user.tier)
        except Exception as e:
            log.exception("send_subscription_activated failed (webhook) for %s: %s", user.email, e)

        return {"status": "ok", "event": event_type, "tier": user.tier}
    except Exception as e:
        log.exception("webhook processing failed (event=%s uid=%s): %s", event_type, user_id, e)
        try:
            db.exec(text("""
                INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
                VALUES (:i, :t, :p, :u, :j)
            """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps({"error": str(e)})))
            db.commit()
        except Exception:
            pass
        return {"status": "error", "event": event_type, "detail": str(e)}

@router.post("/cancel")
# @limiter.limit("6/minute; 60/hour", key_func=key_user_or_ip)
async def cancel_subscription(
    request: Request, response: Response,
    body: Dict[str, Any],
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    body = { "mode": "immediate" | "period_end" }
    """
    mode = (body.get("mode") or "period_end").lower()
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # If already free, normalize flags and return
    if (user.tier or PLAN_FREE).lower() == PLAN_FREE:
        user.tier = PLAN_FREE
        setattr(user, "is_pro_paid_active", False)
        _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
        db.add(user); db.commit()
        return {"status": "ok", "message": "Already on Free"}

    last_paid_at: datetime | None = getattr(user, "last_payment_at", None)
    payment_id: str | None = getattr(user, "last_payment_id", None)

    if mode == "period_end":
        next_renewal = _calc_next_renewal(user)
        _set_cancel_flags_safe(user, enabled=True, next_renewal=next_renewal)
        db.add(user); db.commit()
        try:
            await send_cancellation_confirmed(user.email, immediate=False, effective_at=next_renewal)
        except Exception as e:
            log.exception("send_cancellation_confirmed(period_end) failed for %s: %s", user.email, e)
        return {
            "status": "ok",
            "message": "Cancellation scheduled at period end. Current plan remains active until end of cycle.",
            "current_tier": user.tier,
            "scheduled_plan": PLAN_FREE,
            "next_renewal": next_renewal.isoformat(),
        }

    # immediate cancellation path
    if not last_paid_at:
        user.tier = PLAN_FREE
        setattr(user, "is_pro_paid_active", False)
        _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
        db.add(user); db.commit()
        try:
            await send_cancellation_confirmed(user.email, immediate=True, effective_at=None)
        except Exception as e:
            log.exception("send_cancellation_confirmed(immediate) failed for %s: %s", user.email, e)
        return {"status": "ok", "refunded": False, "reason": "no last payment record"}

    within_window = (_now_utc() - last_paid_at) <= timedelta(days=REFUND_WINDOW_DAYS)

    # Try to compute real usage if helper exists; else default to 'low usage'
    if _monthly_usage_percent is not None:
        try:
            usage_pct = float(_monthly_usage_percent(db, user))  # type: ignore[arg-type]
        except Exception:
            usage_pct = 0.0
    else:
        usage_pct = 0.0
    low_usage = usage_pct <= REFUND_USAGE_MAX_PERCENT

    if within_window and low_usage and payment_id:
        try:
            if GATEWAY == "razorpay":
                refund_resp = await _rzp_refund(payment_id)
            else:
                refund_resp = {"id": f"rfnd_{payment_id or 'dummy'}", "provider": "dummy", "status": "processed"}

            user.tier = PLAN_FREE
            setattr(user, "is_pro_paid_active", False)
            _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
            db.add(user); db.commit()
            try:
                await send_refund_issued(user.email, user.tier, refund_resp.get("id"))
            except Exception as e:
                log.exception("send_refund_issued failed for %s: %s", user.email, e)
            return {"status": "ok", "refunded": True, "refund_id": refund_resp.get("id")}
        except HTTPException as e:
            user.tier = PLAN_FREE
            setattr(user, "is_pro_paid_active", False)
            _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
            db.add(user); db.commit()
            try:
                await send_cancellation_confirmed(user.email, immediate=True, effective_at=None)
            except Exception as e2:
                log.exception("send_cancellation_confirmed(immediate) failed for %s: %s", user.email, e2)
            return {"status": "ok", "refunded": False, "error": e.detail}
    else:
        user.tier = PLAN_FREE
        setattr(user, "is_pro_paid_active", False)
        _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
        db.add(user); db.commit()
        try:
            await send_cancellation_confirmed(user.email, immediate=True, effective_at=None)
        except Exception as e:
            log.exception("send_cancellation_confirmed(immediate) failed for %s: %s", user.email, e)
        reason = []
        if not within_window: reason.append("outside window")
        if not low_usage: reason.append("usage above threshold")
        if not payment_id: reason.append("no payment id")
        return {"status": "ok", "refunded": False, "reason": ", ".join(reason)}
