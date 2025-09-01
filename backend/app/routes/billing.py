# app/routes/billing.py
from __future__ import annotations

import os, json, hmac, hashlib
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select
from sqlalchemy import select as sa_select, text
import logging

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user
from app.config import (
    PLAN_MINI, PLAN_PRO, PLAN_FREE,
    monthly_usage_percent,
)
from app.rate_limit import limiter, key_user_or_ip  # 🔒 SlowAPI per-endpoint limiter

from app.email.events import (
    send_subscription_activated,
    send_payment_failed,
    send_cancellation_confirmed,
    send_refund_issued,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

# -------------------- env & pricing helpers --------------------

GATEWAY = os.getenv("PAYMENT_GATEWAY", "dummy").lower()   # dummy | razorpay
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173")

# Minor units (paise/cents)
PRICE_MINI_INR = int(os.getenv("PRICE_MINI_INR", "14900"))   # ₹149.00
PRICE_PRO_INR  = int(os.getenv("PRICE_PRO_INR",  "50000"))   # ₹500.00
PRICE_MINI_USD = int(os.getenv("PRICE_MINI_USD", "500"))     # $5.00
PRICE_PRO_USD  = int(os.getenv("PRICE_PRO_USD",  "1500"))    # $15.00

# Refund / cancellation policy
REFUND_WINDOW_DAYS       = int(os.getenv("REFUND_WINDOW_DAYS", "2"))
REFUND_USAGE_MAX_PERCENT = float(os.getenv("REFUND_USAGE_MAX_PERCENT", "20"))
BILLING_RETRY_GRACE_DAYS = int(os.getenv("BILLING_RETRY_GRACE_DAYS", "7"))

# Razorpay credentials (used only when PAYMENT_GATEWAY=razorpay)
RZP_KEY_ID         = os.getenv("RZP_KEY_ID", "")
RZP_KEY_SECRET     = os.getenv("RZP_KEY_SECRET", "")
RZP_WEBHOOK_SECRET = os.getenv("RZP_WEBHOOK_SECRET", "")

# VPN guard knobs
VPN_BLOCK_ENABLED      = (os.getenv("VPN_BLOCK_ENABLED", "true").lower() in ("1","true","yes"))
VPN_HEADER_NAME        = os.getenv("VPN_HEADER_NAME", "X-VPN-Detected")
VPN_TRUE_VALUES        = {v.strip().lower() for v in os.getenv("VPN_TRUE_VALUES", "1,true,yes").split(",")}
DEV_FORCE_VPN          = (os.getenv("DEV_FORCE_VPN", "false").lower() in ("1","true","yes"))
DEV_FORCE_COUNTRY      = (os.getenv("DEV_FORCE_COUNTRY") or "").upper().strip()

# -------------------- geo / currency (server authority) --------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _detect_country(request: Request, user: Optional[User] = None) -> str:
    if DEV_FORCE_COUNTRY:
        return DEV_FORCE_COUNTRY

    for h in ("CF-IPCountry", "X-Country-Code", "X-Geo-Country"):
        v = request.headers.get(h)
        if v:
            return v.upper()

    if user is not None:
        c = (getattr(user, "country", None) or "").upper()
        if c:
            return c

    al = request.headers.get("Accept-Language", "")
    if "-IN" in al.upper():
        return "IN"

    return "IN"

def _currency_for_country(cc: str) -> str:
    return "INR" if cc == "IN" else "USD"

def _prices_for_currency(curr: str) -> dict:
    if curr == "INR":
        return {
            "mini_minor": PRICE_MINI_INR,
            "pro_minor":  PRICE_PRO_INR,
            "mini_display": f"₹{PRICE_MINI_INR // 100}/mo",
            "pro_display":  f"₹{PRICE_PRO_INR // 100}/mo",
        }
    def fmt(n: int) -> str:
        return f"${(n/100):.0f}/mo" if n % 100 == 0 else f"${n/100:.2f}/mo"
    return {
        "mini_minor": PRICE_MINI_USD,
        "pro_minor":  PRICE_PRO_USD,
        "mini_display": fmt(PRICE_MINI_USD),
        "pro_display":  fmt(PRICE_PRO_USD),
    }

def _vpn_detected(request: Request) -> bool:
    if DEV_FORCE_VPN:
        return True
    header_val = (request.headers.get(VPN_HEADER_NAME) or "").strip().lower()
    return bool(header_val) and (header_val in VPN_TRUE_VALUES)

# -------------------- Razorpay provider --------------------

async def _rzp_create_payment_link(user: User, plan: str, currency: str, amount_minor: int) -> str:
    payload = {
        "amount": amount_minor,
        "currency": currency,
        "accept_partial": False,
        "reference_id": f"user_{user.id}_{plan}_{int(datetime.utcnow().timestamp())}",
        "description": f"{plan.capitalize()} plan",
        "customer": {"name": user.name or user.email.split('@')[0], "email": user.email},
        "notify": {"email": True, "sms": False},
        "callback_url": f"{APP_BASE_URL}/billing/success",
        "callback_method": "get",
        "notes": {"user_id": str(user.id), "plan": plan},
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
    Normalize Razorpay events. Try to pull user_id/plan from any entity that has notes.
    """
    out = {"event": evt.get("event")}
    p = evt.get("payload", {}) or {}

    # payment_link.* events
    if "payment_link" in p:
        ent = (p["payment_link"].get("entity") or {})
        notes = ent.get("notes") or {}
        out["user_id"] = int(notes.get("user_id")) if str(notes.get("user_id") or "").isdigit() else None
        out["plan"] = (notes.get("plan") or "").lower() or None
        out["status"] = ent.get("status")
        payments = ent.get("payments", [])
        if payments and isinstance(payments, list):
            out["payment_id"] = payments[0].get("id")

    # order.* events
    if "order" in p and not out.get("user_id"):
        ent = (p["order"].get("entity") or {})
        notes = ent.get("notes") or {}
        out["user_id"] = int(notes.get("user_id")) if str(notes.get("user_id") or "").isdigit() else None
        out["plan"] = (notes.get("plan") or "").lower() or None
        out["status"] = ent.get("status")

    # payment.* events (e.g., payment.captured)
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

def _read_cancel_status(user: User) -> Tuple[Optional[str], Optional[datetime], bool]:
    scheduled_plan = None
    next_renewal = None
    cancel_flag = False

    try:
        if hasattr(user, "scheduled_plan"):
            scheduled_plan = getattr(user, "scheduled_plan")
    except Exception:
        pass
    try:
        if hasattr(user, "next_renewal_at"):
            next_renewal = getattr(user, "next_renewal_at")
    except Exception:
        pass
    try:
        if hasattr(user, "cancel_at_period_end"):
            cancel_flag = bool(getattr(user, "cancel_at_period_end"))
    except Exception:
        pass

    return (scheduled_plan, next_renewal, cancel_flag)

# ---- Idempotency guard (pre-change snapshot) ----

def _should_fire_activation_email_snapshot(user: User, new_plan: str, incoming_payment_id: Optional[str]) -> bool:
    old_tier = (getattr(user, "tier", None) or PLAN_FREE).lower()
    old_cancel = bool(getattr(user, "cancel_at_period_end", False))
    old_pid = getattr(user, "last_payment_id", None)

    if old_tier != new_plan:
        return True
    if old_cancel:
        return True
    if incoming_payment_id and old_pid != incoming_payment_id:
        return True
    return False

# -------------------- RL + Webhook infra --------------------

def _ensure_billing_tables(db: Session) -> None:
    """
    Minimal table for webhook idempotency & audits.
    """
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
    """
    Used by SlowAPI's exempt_when: bypass RL when a recognizable signature header is present.
    Cryptographic verification still happens in the handler.
    """
    if GATEWAY == "razorpay":
        return bool(req.headers.get("X-Razorpay-Signature"))
    # generic / future providers
    return bool(req.headers.get("X-Signature"))

def _webhook_event_id(raw: bytes, info: Dict[str, Any]) -> str:
    """
    Best-effort unique id for idempotency:
      - prefer payment_id when present
      - else hash of raw body
    """
    pid = (info.get("payment_id") or "").strip()
    if pid:
        return f"rzp:{pid}"
    return hashlib.sha256(raw).hexdigest()

# -------------------- dispatcher (dummy/razorpay) --------------------

async def _create_checkout_url(request: Request, user: User, plan: str) -> str:
    cc = _detect_country(request, user)
    currency = _currency_for_country(cc)
    prices = _prices_for_currency(currency)
    amount_minor = prices["mini_minor"] if plan == PLAN_MINI else prices["pro_minor"]

    if GATEWAY == "razorpay":
        return await _rzp_create_payment_link(user, plan, currency, amount_minor)

    if GATEWAY == "dummy":
        return f"{APP_BASE_URL}/billing/success?plan={plan}&user={user.id}&currency={currency}&amount={amount_minor}"

    raise HTTPException(status_code=501, detail=f"Provider {GATEWAY} not implemented")

def _verify_and_parse_webhook(request: Request, raw: bytes) -> dict:
    if GATEWAY == "razorpay":
        sig = request.headers.get("X-Razorpay-Signature", "")
        if not sig or not _rzp_verify(sig, raw):
            raise HTTPException(status_code=400, detail="Invalid Razorpay signature")
        evt = json.loads(raw.decode("utf-8"))
        return _rzp_extract(evt)

    # dummy mode (tests)
    evt = json.loads(raw.decode("utf-8"))
    return {
        "event": evt.get("event", "dummy"),
        "user_id": evt.get("user_id"),
        "plan": (evt.get("plan") or "").lower() or None,
        "payment_id": evt.get("payment_id"),
        "status": evt.get("status"),
    }

# -------------------- routes --------------------

@router.get("/guard")
@limiter.limit("120/minute")
def vpn_guard(request: Request):
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
@limiter.limit("60/minute")
def get_prices(request: Request):
    cc = _detect_country(request)
    currency = _currency_for_country(cc)
    p = _prices_for_currency(currency)
    return {"currency": currency, "country": cc, **p}

@router.get("/status")
@limiter.limit("60/minute")
def billing_status(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
    request: Request = None,
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    scheduled_plan, next_renewal_dt, cancel_flag = _read_cancel_status(user)

    resp = {
        "tier": user.tier or "free",
        "manage_url": None,
        "scheduled_plan": scheduled_plan,
        "next_renewal": next_renewal_dt.isoformat() if isinstance(next_renewal_dt, datetime) else None,
        "cancel_at_period_end": bool(cancel_flag),
    }
    if request is not None:
        cc = _detect_country(request, user)
        resp["currency"] = _currency_for_country(cc)
        resp["country"] = cc
        resp["vpn_blocked"] = (_vpn_detected(request) and VPN_BLOCK_ENABLED)
    return resp

@router.post("/checkout")
@limiter.limit("6/minute; 60/hour")
async def start_checkout(
    body: Dict[str, Any],
    request: Request,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    body = { "plan": "mini" | "pro" }

    Razorpay: return payment link (no state, no email).
    Dummy: apply plan + renewal AND send activation email (no webhook in dev).
    """
    if _vpn_detected(request) and VPN_BLOCK_ENABLED:
        raise HTTPException(status_code=403, detail="Billing disabled while VPN/proxy is detected. Please disable VPN and retry.")

    plan = (body.get("plan") or "").lower().strip()
    if plan not in {PLAN_MINI, PLAN_PRO}:
        raise HTTPException(status_code=400, detail="Plan must be 'mini' or 'pro'")

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if GATEWAY == "razorpay":
        url = await _create_checkout_url(request, user, plan)
        return {"url": url}

    if GATEWAY == "dummy":
        cc = _detect_country(request, user)
        currency = _currency_for_country(cc)
        prices = _prices_for_currency(currency)
        amount_minor = prices["mini_minor"] if plan == PLAN_MINI else prices["pro_minor"]

        user.tier = plan
        _set_payment_meta_safe(user, f"dummy_{int(_now_utc().timestamp())}")
        try:
            if hasattr(user, "next_renewal_at"):
                setattr(user, "next_renewal_at", _now_utc() + timedelta(days=30))
        except Exception:
            pass
        _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
        db.add(user); db.commit()

        # Send immediately in dummy mode (no webhook)
        try:
            await send_subscription_activated(user.email, plan)
        except Exception as e:
            log.exception("send_subscription_activated failed (dummy checkout) for %s: %s", user.email, e)

        url = f"{APP_BASE_URL}/billing/success?plan={plan}&user={user.id}&currency={currency}&amount={amount_minor}"
        return {"url": url}

    raise HTTPException(status_code=501, detail=f"Provider {GATEWAY} not implemented")

@router.post("/webhook")
@limiter.limit("30/minute", exempt_when=_is_trusted_webhook)  # bypass RL for signed gateway calls
async def handle_webhook(
    request: Request,
    db: Session = Depends(get_session),
):
    """
    Webhook:
      • Razorpay: accept 'payment_link.paid', 'order.paid', 'payment.captured'
      • Dummy: ignore paid path (we email in /checkout)
      • Row-lock user to avoid concurrent duplicate sends
      • Snapshot guard to avoid resends on retries/out-of-order deliveries
      • Idempotent via billing_event(event_id UNIQUE)
    """
    raw = await request.body()

    # Verify + parse provider payload
    info = _verify_and_parse_webhook(request, raw)

    # Ensure idempotency infra
    _ensure_billing_tables(db)
    event_id = _webhook_event_id(raw, info)
    event_type = (info.get("event") or "").lower()
    provider = GATEWAY

    # Idempotency check
    already = db.exec(text("SELECT 1 FROM public.billing_event WHERE event_id = :e").bindparams(e=event_id)).first()
    if already:
        return {"status": "ok", "idempotent": True}

    user_id = info.get("user_id")
    plan = info.get("plan")
    payment_id = info.get("payment_id")

    if not user_id:
        # Record and acknowledge so gateway doesn't retry forever
        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=None, j=json.dumps(info)))
        db.commit()
        return {"status": "ignored", "reason": "no user_id", "event": event_type}

    if GATEWAY == "razorpay":
        paid_events = {"payment_link.paid", "order.paid", "payment.captured"}
        is_paid = (event_type in paid_events)
    else:
        is_paid = False

    # Payment failures (Razorpay): notify, record, and ack
    if event_type in {"payment_link.failed", "order.payment.failed"}:
        try:
            user = db.get(User, user_id)
            if user:
                await send_payment_failed(user.email)
        except Exception as e:
            log.exception("send_payment_failed failed (event=%s uid=%s): %s", event_type, user_id, e)
        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps(info)))
        db.commit()
        return {"status": "ok", "event": event_type}

    if not (is_paid and plan in {PLAN_MINI, PLAN_PRO}):
        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps(info)))
        db.commit()
        return {"status": "ignored", "event": event_type}

    # ---- Serialize per-user with row lock ----
    try:
        with db.begin():
            locked_stmt = sa_select(User).where(User.id == user_id).with_for_update()
            user = db.exec(locked_stmt).first()
            if not user:
                # Still record event so retries won't reprocess
                db.exec(text("""
                    INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
                    VALUES (:i, :t, :p, :u, :j)
                """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps(info)))
                db.commit()
                return {"status": "ignored", "reason": "user missing", "event": event_type}

            should_notify = _should_fire_activation_email_snapshot(user, plan, payment_id)
            pre_tier = (user.tier or PLAN_FREE).lower()
            pre_cancel = bool(getattr(user, "cancel_at_period_end", False))
            pre_pid = getattr(user, "last_payment_id", None)

            user.tier = plan
            _set_payment_meta_safe(user, payment_id)
            try:
                if hasattr(user, "next_renewal_at"):
                    setattr(user, "next_renewal_at", _now_utc() + timedelta(days=30))
            except Exception:
                pass
            _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
            db.add(user)

        # Record event AFTER successful state update (keeps idempotency)
        db.exec(text("""
            INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
            VALUES (:i, :t, :p, :u, :j)
        """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps(info)))
        db.commit()

        if should_notify:
            try:
                await send_subscription_activated(user.email, plan)
            except Exception as e:
                log.exception("send_subscription_activated failed (webhook) for %s: %s", user.email, e)
        else:
            log.info(
                "Skip activation email (duplicate) uid=%s plan=%s event=%s pid=%s [pre: tier=%s cancel=%s pid=%s]",
                user_id, plan, event_type, payment_id, pre_tier, pre_cancel, pre_pid
            )

        return {"status": "ok", "event": event_type, "tier": user.tier}
    except Exception as e:
        log.exception("webhook processing failed (event=%s uid=%s): %s", event_type, user_id, e)
        # Record failure attempt as well (no unique violation since event_id not inserted yet if we crashed earlier)
        try:
            db.exec(text("""
                INSERT INTO public.billing_event (event_id, event_type, provider, user_id, payload)
                VALUES (:i, :t, :p, :u, :j)
            """).bindparams(i=event_id, t=event_type, p=provider, u=user_id, j=json.dumps({"error": str(e)})))
            db.commit()
        except Exception:
            pass
        return {"status": "error", "event": event_type, "detail": str(e)}

@router.post("/dev/activate")
@limiter.limit("10/minute", key_func=key_user_or_ip)
async def dev_activate(
    request: Request,                          # <-- required by SlowAPI
    body: Dict[str, Any],
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    DEV only: immediately set a plan. (No email here; use /dev/test-email to test templates.)
    Requires PAYMENT_GATEWAY=dummy.
    """
    if GATEWAY != "dummy":
        raise HTTPException(status_code=404, detail="Not available")

    plan = (body.get("plan") or "").lower().strip()
    if plan not in {PLAN_MINI, PLAN_PRO}:
        raise HTTPException(status_code=400, detail="Plan must be 'mini' or 'pro'")

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.tier = plan
    _set_payment_meta_safe(user, f"dummy_{int(datetime.now().timestamp())}")
    try:
        if hasattr(user, "next_renewal_at"):
            setattr(user, "next_renewal_at", _now_utc() + timedelta(days=30))
    except Exception:
        pass
    _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
    db.add(user); db.commit()

    return {"status": "ok", "tier": user.tier, "dev": True}

@router.post("/cancel")
@limiter.limit("6/minute; 60/hour", key_func=key_user_or_ip)
async def cancel_subscription(
    request: Request,                          # <-- required by SlowAPI
    body: Dict[str, Any],
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    body = { "mode": "immediate" | "period_end" }
    - period_end: keep plan active until next_renewal; schedule downgrade (no mid-month switch)
    - immediate: downgrade right now; refund eligibility window still applies
    """
    mode = (body.get("mode") or "period_end").lower()
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.tier not in {PLAN_MINI, PLAN_PRO}:
        user.tier = PLAN_FREE
        db.add(user); db.commit()
        return {"status": "ok", "message": "Already on free"}

    last_paid_at: datetime | None = getattr(user, "last_payment_at", None)
    payment_id: str | None = getattr(user, "last_payment_id", None)

    # === No mid-month switch (requested behavior) ===
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

    # === immediate path w/ refund rules ===
    if not last_paid_at:
        user.tier = PLAN_FREE
        _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
        db.add(user); db.commit()
        try:
            await send_cancellation_confirmed(user.email, immediate=True, effective_at=None)
        except Exception as e:
            log.exception("send_cancellation_confirmed(immediate) failed for %s: %s", user.email, e)
        return {"status": "ok", "refunded": False, "reason": "no last payment record"}

    within_window = (_now_utc() - last_paid_at) <= timedelta(days=REFUND_WINDOW_DAYS)
    usage_pct = monthly_usage_percent(db, user)
    low_usage = usage_pct <= REFUND_USAGE_MAX_PERCENT

    if within_window and low_usage and payment_id:
        try:
            if GATEWAY == "razorpay":
                refund_resp = await _rzp_refund(payment_id)
            else:
                refund_resp = {"id": f"rfnd_{payment_id or 'dummy'}", "provider": "dummy", "status": "processed"}
            user.tier = PLAN_FREE
            _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
            db.add(user); db.commit()
            try:
                await send_refund_issued(user.email, user.tier, refund_resp.get("id"))
            except Exception as e:
                log.exception("send_refund_issued failed for %s: %s", user.email, e)
            return {"status": "ok", "refunded": True, "refund_id": refund_resp.get("id")}
        except HTTPException as e:
            user.tier = PLAN_FREE
            _set_cancel_flags_safe(user, enabled=False, next_renewal=None)
            db.add(user); db.commit()
            try:
                await send_cancellation_confirmed(user.email, immediate=True, effective_at=None)
            except Exception as e2:
                log.exception("send_cancellation_confirmed(immediate) failed for %s: %s", user.email, e2)
            return {"status": "ok", "refunded": False, "error": e.detail}
    else:
        user.tier = PLAN_FREE
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

@router.post("/dev/test-email")
@limiter.limit("10/minute", key_func=key_user_or_ip)
async def dev_test_email(
    request: Request,                          # <-- required by SlowAPI
    body: Dict[str, Any],
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Dev-only helper to verify email sending and template fallbacks.
    body = { "kind": "activated" | "cancel_immediate" | "cancel_period_end" | "payment_failed" | "refund" }
    Requires PAYMENT_GATEWAY=dummy.
    """
    if GATEWAY != "dummy":
        raise HTTPException(status_code=404, detail="Not available")

    kind = (body.get("kind") or "").lower().strip()
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        if kind == "activated":
            await send_subscription_activated(user.email, user.tier or PLAN_PRO)
        elif kind == "cancel_immediate":
            await send_cancellation_confirmed(user.email, immediate=True, effective_at=None)
        elif kind == "cancel_period_end":
            effective = _calc_next_renewal(user)
            await send_cancellation_confirmed(user.email, immediate=False, effective_at=effective)
        elif kind == "payment_failed":
            await send_payment_failed(user.email)
        elif kind == "refund":
            await send_refund_issued(user.email, user.tier or PLAN_PRO, refund_id="rfnd_dev_123")
        else:
            raise HTTPException(status_code=400, detail="Unknown kind")
    except Exception as e:
        log.exception("dev_test_email failed (%s) for %s: %s", kind, user.email, e)
        return {"status": "error", "kind": kind, "detail": str(e)}

    return {"status": "ok", "kind": kind}
