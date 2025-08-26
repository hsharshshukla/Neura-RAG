# app/utils/mailer.py
from __future__ import annotations
import os, asyncio

from app.email.service import make_default_service, render_template, make_from_env
from app.email.models import EmailMessage, EmailAddress

def send_password_reset_email(to_email: str, reset_link: str, expires_minutes: int | None = None) -> None:
    """
    Fire-and-forget password reset email using the SMTP-backed EmailService.
    Respects DEV_EMAIL_LOG_ONLY; uses templates when available.
    """
    if str(os.getenv("DEV_EMAIL_LOG_ONLY", "false")).lower() in ("1", "true", "yes", "on"):
        print(f"[DEV MAIL] Reset link for {to_email}: {reset_link}")
        return

    svc = make_default_service()
    frm = make_from_env()

    ttl = expires_minutes or int(os.getenv("RESET_TOKEN_TTL_MIN", "30"))
    # Use templates if present, otherwise a minimal fallback
    try:
        html, txt = render_template(
            "reset_password",
            user_name=to_email.split("@")[0],
            reset_url=reset_link,
            expires_minutes=ttl,
        )
    except Exception:
        html = f"<p>Reset your password: <a href='{reset_link}'>{reset_link}</a></p><p>This link expires in {ttl} minutes.</p>"
        txt  = f"Reset your password: {reset_link}\nThis link expires in {ttl} minutes."

    msg = EmailMessage(
        subject="Reset your password",
        **{"from": frm},
        to=[EmailAddress(email=to_email)],
        html=html,
        text=txt,
    )

    # Schedule send without blocking the request
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(svc.send(msg))
    except RuntimeError:
        asyncio.run(svc.send(msg))

# app/utils/mailer.py  (append below your existing reset function)
def send_email_verification(to_email: str, verify_link: str, expires_hours: int | None = None) -> None:
    if str(os.getenv("DEV_EMAIL_LOG_ONLY", "false")).lower() in ("1","true","yes","on"):
        print(f"[DEV MAIL] Verify link for {to_email}: {verify_link}")
        return

    svc = make_default_service()
    frm = make_from_env()
    hrs = expires_hours or int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "24"))

    try:
        html, txt = render_template(
            "verify_email",
            user_name=to_email.split("@")[0],
            verify_url=verify_link,
            expires_hours=hrs,
        )
    except Exception:
        html = f"<p>Verify your email: <a href='{verify_link}'>{verify_link}</a></p><p>This link expires in {hrs} hours.</p>"
        txt  = f"Verify your email: {verify_link}\nThis link expires in {hrs} hours."

    msg = EmailMessage(
        subject="Verify your email",
        **{"from": frm},
        to=[EmailAddress(email=to_email)],
        html=html,
        text=txt,
    )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(svc.send(msg))
    except RuntimeError:
        asyncio.run(svc.send(msg))

