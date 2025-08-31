# app/email/events.py
from __future__ import annotations

import os
import logging
from typing import Optional
from datetime import datetime, timezone

# We only need render_template here; sending is done via utils.mailer
from app.email.service import render_template
from app.email.models import EmailAddress

# Reuse the *known-good* path for building + sending mail
from app.utils.mailer import (
    _build_email_message as _build_msg,
    _dispatch as _send_msg,
)

log = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173")

# ------------------------- helpers -------------------------

def _bool_env(name: str, default: bool = False) -> bool:
    v = (os.getenv(name, str(default)) or "").strip().lower()
    return v in ("1", "true", "yes", "on")

def _subject(s: str) -> str:
    pref = (os.getenv("EMAIL_SUBJECT_PREFIX") or "").strip()
    return f"{pref} {s}".strip() if pref else s

def _resolve_from_addr() -> EmailAddress:
    """
    Prefer EMAIL_FROM_ADDRESS/EMAIL_FROM_NAME, otherwise fall back to FROM_EMAIL,
    and finally a safe default. Mirrors utils.mailer behavior to avoid surprises.
    """
    env_from = (os.getenv("EMAIL_FROM_ADDRESS") or "").strip()
    env_name = (os.getenv("EMAIL_FROM_NAME") or "").strip() or None
    if env_from:
        return EmailAddress(email=env_from, name=env_name)

    legacy = (os.getenv("FROM_EMAIL") or "").strip()
    if legacy:
        return EmailAddress(email=legacy, name=env_name)

    return EmailAddress(email="no-reply@localhost")

def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%b %d, %Y")

# ------------------------- core sender (delegates to mailer.py) -------------------------

async def _send(subject: str, to_email: str, html: str, text: str = "") -> None:
    """
    Build + dispatch using the same robust builder/dispatcher used by reset/verify emails.
    This guarantees identical field mapping and SMTP behavior.
    """
    if _bool_env("DISABLE_EMAIL", False):
        log.warning("[MAIL] DISABLE_EMAIL=true; skipping send to %s (%s)", to_email, subject)
        return
    if _bool_env("DEV_EMAIL_LOG_ONLY", False):
        log.info("[DEV MAIL] Would send to %s: %s", to_email, subject)
        return

    from_addr = _resolve_from_addr()

    # Build message with alias-aware model validation (handles from/from_/html/html_body etc.)
    msg = _build_msg(
        subject=_subject(subject),
        from_addr=from_addr,
        to_email=to_email,
        html=html,
        txt=text or html,
    )

    # Send via the same dispatcher used elsewhere (respects EMAIL_DEBUG_SYNC etc.)
    _send_msg(msg)
    log.info("[MAIL][events] queued %r to %s", subject, to_email)

# ------------------------- event emails -------------------------

async def send_subscription_activated(to_email: str, plan: str) -> None:
    """
    Fired when payment succeeds and plan is applied.
    Template key: subscription_activated
    Vars provided: plan, plan_name, manage_url
    """
    plan_name = (plan or "").strip().capitalize() or "Pro"
    try:
        html, txt = render_template(
            "subscription_activated",
            user_name=to_email.split("@")[0],
            plan=plan,
            plan_name=plan_name,
            manage_url=f"{APP_BASE_URL}/billing",
        )
    except Exception:
        html = (
            f"<p>Hello {to_email.split('@')[0]},</p>"
            f"<p>Your <b>{plan_name}</b> subscription is now active. 🎉</p>"
            f"<p>You can manage your plan here: <a href='{APP_BASE_URL}/billing'>Billing</a></p>"
            "<p>— The Neura team</p>"
        )
        txt = (
            f"Hello {to_email.split('@')[0]},\n"
            f"Your {plan_name} subscription is now active.\n"
            f"Manage: {APP_BASE_URL}/billing\n"
            "— The Neura team\n"
        )
    await _send(f"Your {plan_name} subscription is active", to_email, html, txt)

async def send_payment_failed(to_email: str) -> None:
    """
    Fired on payment failure / retry grace start.
    Template key: payment_failed
    Vars: manage_url
    """
    try:
        html, txt = render_template(
            "payment_failed",
            user_name=to_email.split("@")[0],
            manage_url=f"{APP_BASE_URL}/billing",
        )
    except Exception:
        html = (
            f"<p>Hello {to_email.split('@')[0]},</p>"
            "<p>Your recent payment attempt failed. Please update your payment method to avoid interruption.</p>"
            f"<p>Update here: <a href='{APP_BASE_URL}/billing'>Billing</a></p>"
            "<p>— The Neura team</p>"
        )
        txt = (
            f"Hello {to_email.split('@')[0]},\n"
            "Your recent payment attempt failed. Please update your payment method.\n"
            f"Billing: {APP_BASE_URL}/billing\n"
            "— The Neura team\n"
        )
    await _send("Payment failed — action required", to_email, html, txt)

async def send_cancellation_confirmed(
    to_email: str,
    immediate: bool = True,
    effective_at: Optional[datetime] = None,
) -> None:
    """
    One template for both scenarios:
      - immediate=True  -> ends now
      - immediate=False -> ends on effective_at
    Template key: cancellation_confirmed
    Vars: immediate (bool), effective_date/effective_at, reactivate_url/manage_url
    """
    date_str = _fmt_dt(effective_at)
    try:
        html, txt = render_template(
            "cancellation_confirmed",
            user_name=to_email.split("@")[0],
            immediate=bool(immediate),
            effective_date=date_str,
            effective_at=date_str,
            reactivate_url=f"{APP_BASE_URL}/billing",
            manage_url=f"{APP_BASE_URL}/billing",
        )
    except Exception:
        if immediate:
            html = (
                f"<p>Hello {to_email.split('@')[0]},</p>"
                "<p>Your subscription has been cancelled effective immediately. "
                f"You can reactivate anytime here: <a href='{APP_BASE_URL}/billing'>Billing</a></p>"
                "<p>— The Neura team</p>"
            )
            txt = (
                f"Hello {to_email.split('@')[0]},\n"
                "Your subscription has been cancelled effective immediately.\n"
                f"Reactivate: {APP_BASE_URL}/billing\n"
                "— The Neura team\n"
            )
        else:
            when = date_str or "the end of your current billing period"
            html = (
                f"<p>Hello {to_email.split('@')[0]},</p>"
                f"<p>Your subscription will end on <b>{when}</b>. "
                f"You’ll be moved to the Free plan afterward. You can change this anytime here: "
                f"<a href='{APP_BASE_URL}/billing'>Billing</a></p>"
                "<p>— The Neura team</p>"
            )
            txt = (
                f"Hello {to_email.split('@')[0]},\n"
                f"Your subscription will end on {when}. You’ll be moved to the Free plan afterward.\n"
                f"Manage: {APP_BASE_URL}/billing\n"
                "— The Neura team\n"
            )
    subject = "Cancellation confirmed" if immediate else "Cancellation scheduled"
    await _send(subject, to_email, html, txt)

async def send_refund_issued(to_email: str, tier: str, refund_id: Optional[str] = None) -> None:
    """
    Optional notification when an immediate cancel qualifies for a refund.
    Template key: refund_issued
    Vars: tier/plan_name, refund_id
    """
    plan_name = (tier or "Pro").capitalize()
    rid = refund_id or ""
    try:
        html, txt = render_template(
            "refund_issued",
            user_name=to_email.split("@")[0],
            tier=tier,
            plan_name=plan_name,
            refund_id=rid,
        )
    except Exception:
        show_id = rid or "N/A"
        html = (
            f"<p>Hello {to_email.split('@')[0]},</p>"
            f"<p>Your refund has been issued. Refund ID: <b>{show_id}</b>.</p>"
            "<p>— The Neura team</p>"
        )
        txt = (
            f"Hello {to_email.split('@')[0]},\n"
            f"Your refund has been issued. Refund ID: {show_id}\n"
            "— The Neura team\n"
        )
    await _send("Refund issued", to_email, html, txt)
