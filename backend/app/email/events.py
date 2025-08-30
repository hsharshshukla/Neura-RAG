# app/email/events.py
from __future__ import annotations
import os
from typing import Optional
from datetime import datetime

from app.email.service import make_default_service, make_from_env, render_template
from app.email.models import EmailMessage, EmailAddress

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173")



async def _send(subject: str, to_email: str, html: str, text: str = "") -> None:
    """
    Thin async sender that uses your EmailService and your EmailMessage schema.
    NOTE: EmailMessage expects `from_`, not `from_email`.
    """
    svc = make_default_service()
    frm = make_from_env()  # could be EmailAddress or a simple object with email/name

    from_addr = frm if isinstance(frm, EmailAddress) else EmailAddress(
        email=getattr(frm, "email", str(frm)),
        name=getattr(frm, "name", None),
    )

    msg = EmailMessage(
        subject=subject,
        from_=from_addr,                 # <-- critical
        to=[EmailAddress(email=to_email)],
        html_body=html,                  # keep your field names
        text_body=text or html,
    )
    await svc.send(msg)


async def send_subscription_activated(to_email: str, plan: str) -> None:
    """
    Fired when payment succeeds and plan is applied.
    """
    plan_name = (plan or "").strip().capitalize() or "Pro"
    try:
        html, txt = render_template(
            "subscription_activated",
            user_name=to_email.split("@")[0],
            plan_name=plan_name,
            manage_url=f"{APP_BASE_URL}/billing",
        )
    except Exception:
        html = (
            f"<p>Hello {to_email.split('@')[0]},</p>"
            f"<p>Your <b>{plan_name}</b> subscription is now active. 🎉</p>"
            f"<p>You can manage your plan here: <a href='{APP_BASE_URL}/billing'>Billing</a></p>"
        )
        txt = (
            f"Hello {to_email.split('@')[0]},\n"
            f"Your {plan_name} subscription is now active.\n"
            f"Manage: {APP_BASE_URL}/billing\n"
        )
    await _send(f"Your {plan_name} subscription is active", to_email, html, txt)


async def send_payment_failed(to_email: str) -> None:
    """
    Fired on payment failure / retry grace start.
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
        )
        txt = (
            f"Hello {to_email.split('@')[0]},\n"
            "Your recent payment attempt failed. Please update your payment method.\n"
            f"Billing: {APP_BASE_URL}/billing\n"
        )
    await _send("Payment failed — action required", to_email, html, txt)


async def send_cancellation_confirmed(
    to_email: str,
    immediate: bool = True,
    effective_at: datetime | None = None,
) -> None:
    """
    Sends a single, clear email for both cases:
      - immediate: ends now
      - period_end: ends on effective_at (shows a date)
    """
    date_str = effective_at.strftime("%b %d, %Y") if isinstance(effective_at, datetime) else None

    try:
        html, txt = render_template(
            "cancellation_confirmed",
            user_name=to_email.split("@")[0],
            immediate=bool(immediate),
            effective_date=date_str,  # only used when not immediate
            reactivate_url=f"{APP_BASE_URL}/billing",
        )
    except Exception:
        if immediate:
            html = (
                f"<p>Hello {to_email.split('@')[0]},</p>"
                "<p>Your subscription has been cancelled effective immediately. "
                f"You can reactivate anytime here: <a href='{APP_BASE_URL}/billing'>Billing</a></p>"
            )
            txt = (
                f"Hello {to_email.split('@')[0]},\n"
                "Your subscription has been cancelled effective immediately.\n"
                f"Reactivate: {APP_BASE_URL}/billing\n"
            )
        else:
            when = date_str or "the end of the current billing period"
            html = (
                f"<p>Hello {to_email.split('@')[0]},</p>"
                f"<p>Your subscription will end on <b>{when}</b>. "
                f"You can change this anytime here: <a href='{APP_BASE_URL}/billing'>Billing</a></p>"
            )
            txt = (
                f"Hello {to_email.split('@')[0]},\n"
                f"Your subscription will end on {when}.\n"
                f"Manage: {APP_BASE_URL}/billing\n"
            )
    await _send("Cancellation confirmed", to_email, html, txt)


async def send_refund_issued(to_email: str, tier: str, refund_id: Optional[str] = None) -> None:
    """
    Fired when a refund is processed (immediate cancel within policy).
    """
    try:
        html, txt = render_template(
            "refund_issued",
            user_name=to_email.split("@")[0],
            plan_name=(tier or "Pro").capitalize(),
            refund_id=refund_id or "",
        )
    except Exception:
        rid = refund_id or "N/A"
        html = (
            f"<p>Hello {to_email.split('@')[0]},</p>"
            f"<p>Your refund has been issued. Refund ID: <b>{rid}</b>.</p>"
        )
        txt = (
            f"Hello {to_email.split('@')[0]},\n"
            f"Your refund has been issued. Refund ID: {rid}\n"
        )
    await _send("Refund issued", to_email, html, txt)
