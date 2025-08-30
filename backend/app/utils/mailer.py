# app/utils/mailer.py
from __future__ import annotations
import os
import asyncio
import logging

from app.email.service import make_default_service, render_template, make_from_env
from app.email.models import EmailMessage, EmailAddress

log = logging.getLogger(__name__)

# ------------------------- helpers -------------------------

def _bool_env(name: str, default: bool = False) -> bool:
    v = (os.getenv(name, str(default)) or "").strip().lower()
    return v in ("1", "true", "yes", "on")

def _from_env_addr() -> EmailAddress:
    """
    Convert whatever make_from_env() returns into an EmailAddress.
    Supports either an EmailAddress instance or any object with .email/.name.
    """
    frm = make_from_env()
    if isinstance(frm, EmailAddress):
        return frm
    return EmailAddress(
        email=getattr(frm, "email", str(frm)),
        name=getattr(frm, "name", None),
    )

def _send_fire_and_forget(msg: EmailMessage) -> None:
    """
    Schedule async send without blocking the request thread.
    Falls back to running a loop if we aren't in one (CLI/worker).
    """
    # honor kill switches
    if _bool_env("DISABLE_EMAIL", False):
        to_list = ", ".join(getattr(a, "email", "") for a in (msg.to or []))
        log.warning("[MAIL] DISABLE_EMAIL=true; skipping send to %s", to_list)
        return

    svc = make_default_service()

    async def _go():
        await svc.send(msg)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_go())
    except RuntimeError:
        asyncio.run(_go())

# ------------------------- public API -------------------------

def send_password_reset_email(to_email: str, reset_link: str, expires_minutes: int | None = None) -> None:
    """
    Fire-and-forget password reset email using the SMTP-backed EmailService.
    Respects DEV_EMAIL_LOG_ONLY; uses templates when available.
    """
    if _bool_env("DEV_EMAIL_LOG_ONLY", False):
        print(f"[DEV MAIL] Reset link for {to_email}: {reset_link}")
        return

    from_addr = _from_env_addr()
    ttl = expires_minutes or int(os.getenv("RESET_TOKEN_TTL_MIN", "30"))

    # Prefer templates; fall back cleanly if missing
    try:
        html, txt = render_template(
            "reset_password",
            user_name=to_email.split("@")[0],
            reset_url=reset_link,
            expires_minutes=ttl,
        )
    except Exception as e:
        log.exception("render_template(reset_password) failed; using fallback: %s", e)
        html = (
            "<p>Hello,</p>"
            f"<p>Reset your password: <a href='{reset_link}'>{reset_link}</a></p>"
            f"<p>This link expires in {ttl} minutes.</p>"
        )
        txt = (
            "Hello,\n"
            f"Reset your password: {reset_link}\n"
            f"This link expires in {ttl} minutes.\n"
        )

    msg = EmailMessage(
        subject="Reset your password",
        from_=from_addr,                           # <-- correct field name
        to=[EmailAddress(email=to_email)],
        html_body=html,                            # <-- correct field name
        text_body=txt,                             # <-- correct field name
    )
    log.info("[MAIL] sending password reset email to %s from %s", to_email, from_addr.email)
    _send_fire_and_forget(msg)


def send_email_verification(to_email: str, verify_link: str, expires_hours: int | None = None) -> None:
    """
    Fire-and-forget email verification message.
    """
    if _bool_env("DEV_EMAIL_LOG_ONLY", False):
        print(f"[DEV MAIL] Verify link for {to_email}: {verify_link}")
        return

    from_addr = _from_env_addr()
    hrs = expires_hours or int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "24"))

    try:
        html, txt = render_template(
            "verify_email",
            user_name=to_email.split("@")[0],
            verify_url=verify_link,
            expires_hours=hrs,
        )
    except Exception as e:
        log.exception("render_template(verify_email) failed; using fallback: %s", e)
        html = (
            "<p>Hello,</p>"
            f"<p>Verify your email: <a href='{verify_link}'>{verify_link}</a></p>"
            f"<p>This link expires in {hrs} hours.</p>"
        )
        txt = (
            "Hello,\n"
            f"Verify your email: {verify_link}\n"
            f"This link expires in {hrs} hours.\n"
        )

    msg = EmailMessage(
        subject="Verify your email",
        from_=from_addr,                           # <-- correct field name
        to=[EmailAddress(email=to_email)],
        html_body=html,                            # <-- correct field name
        text_body=txt,                             # <-- correct field name
    )
    log.info("[MAIL] sending verification email to %s from %s", to_email, from_addr.email)
    _send_fire_and_forget(msg)
