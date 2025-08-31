# app/utils/mailer.py
from __future__ import annotations
import os
import asyncio
import logging
from typing import Dict, Any, Optional, List

from app.email.service import make_default_service, render_template, make_from_env
from app.email.models import EmailMessage, EmailAddress

log = logging.getLogger(__name__)

# ------------------------- env + helpers -------------------------

def _bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name, str(default)) or "").strip().lower()
    return v in ("1", "true", "yes", "on")

def _resolve_from_addr() -> EmailAddress:
    """
    Priority:
      1) EMAIL_FROM_ADDRESS / EMAIL_FROM_NAME
      2) make_from_env() (EmailAddress or any object with .email/.name)
      3) FROM_EMAIL (legacy)
      4) safe fallback
    """
    env_from = (os.getenv("EMAIL_FROM_ADDRESS") or "").strip()
    env_name = (os.getenv("EMAIL_FROM_NAME") or "").strip() or None
    if env_from:
        return EmailAddress(email=env_from, name=env_name)

    try:
        frm = make_from_env()
        if isinstance(frm, EmailAddress):
            return frm
        email = getattr(frm, "email", None) or (os.getenv("FROM_EMAIL") or "").strip()
        name  = getattr(frm, "name", None) or env_name
        if email:
            return EmailAddress(email=email, name=name)
    except Exception as e:
        log.warning("make_from_env() failed, falling back to FROM_EMAIL: %s", e)

    legacy = (os.getenv("FROM_EMAIL") or "").strip()
    if legacy:
        return EmailAddress(email=legacy, name=env_name)

    return EmailAddress(email="no-reply@localhost")

async def _send_async(msg: EmailMessage) -> None:
    svc = make_default_service()
    await svc.send(msg)
    to_list = ", ".join(a.email for a in (msg.to or []))
    log.info("[MAIL] sent to %s (subject=%r)", to_list, msg.subject)

def _dispatch(msg: EmailMessage) -> None:
    """
    EMAIL_DEBUG_SYNC=true -> send synchronously (so SMTP errors appear immediately in logs)
    otherwise fire-and-forget.
    """
    if _bool("DISABLE_EMAIL", False):
        to_list = ", ".join(getattr(a, "email", "") for a in (msg.to or []))
        log.warning("[MAIL] DISABLE_EMAIL=true; skipping send to %s", to_list)
        return
    if _bool("DEV_EMAIL_LOG_ONLY", False):
        to_list = ", ".join(getattr(a, "email", "") for a in (msg.to or []))
        log.info("[DEV MAIL] Would send to %s (subject=%r)", to_list, msg.subject)
        return

    if _bool("EMAIL_DEBUG_SYNC", False):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # no running loop (CLI) -> run inline
            asyncio.run(_send_async(msg))
            return
        # we do have a loop; schedule but errors will surface in server logs
        loop.create_task(_send_async(msg))
        return

    # default: fire-and-forget
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_async(msg))
    except RuntimeError:
        asyncio.run(_send_async(msg))

# ------------------------- robust EmailMessage builder -------------------------

def _try_build_with_alias(payload: Dict[str, Any]) -> Optional[EmailMessage]:
    """
    Try to validate using alias-based keys first (e.g., 'from', 'html', 'text').
    Works for Pydantic v2 (model_validate) and v1 (parse_obj) without
    running into Python keyword arg issues.
    """
    try:
        if hasattr(EmailMessage, "model_validate"):  # Pydantic v2
            return EmailMessage.model_validate(payload)
        else:  # Pydantic v1
            return EmailMessage.parse_obj(payload)
    except Exception:
        return None

def _build_email_message(subject: str, from_addr: EmailAddress, to_email: str, html: str, txt: str) -> EmailMessage:
    """
    Build EmailMessage regardless of the model’s internal field names.
    We attempt multiple payload shapes until one validates.
    NOTE: we use dict-based validation to avoid Python's 'from' keyword issues.
    """
    candidates: List[Dict[str, Any]] = [
        # 1) Common alias-first shape
        {
            "subject": subject,
            "from": from_addr,  # alias
            "to": [EmailAddress(email=to_email)],
            "html": html,       # alias
            "text": txt,        # alias
        },
        # 2) Typical explicit field names with underscores
        {
            "subject": subject,
            "from_": from_addr,
            "to": [EmailAddress(email=to_email)],
            "html_body": html,
            "text_body": txt,
        },
        # 3) Alternative naming sometimes used
        {
            "subject": subject,
            "from_email": from_addr,
            "recipients": [EmailAddress(email=to_email)],
            "html_body": html,
            "text_body": txt,
        },
    ]

    last_err: Optional[Exception] = None
    for p in candidates:
        try:
            msg = _try_build_with_alias(p)
            if msg is not None:
                return msg
        except Exception as e:
            last_err = e

    # If none worked, raise a clear error with available keys
    raise ValueError(
        f"Unable to instantiate EmailMessage with any known field mapping. "
        f"Last error: {last_err}"
    )

# ------------------------- public API -------------------------

def send_password_reset_email(to_email: str, reset_link: str, expires_minutes: int | None = None) -> None:
    """
    Password reset email. Uses templates if available; clean fallback otherwise.
    """
    from_addr = _resolve_from_addr()
    ttl = expires_minutes or int(os.getenv("RESET_TOKEN_TTL_MIN", "30"))

    try:
        html, txt = render_template(
            "reset_password",
            user_name=to_email.split("@")[0],
            reset_url=reset_link,
            expires_minutes=ttl,
        )
    except Exception as e:
        log.warning("render_template(reset_password) failed; using fallback: %s", e)
        html = (
            "<p>Hello,</p>"
            f"<p>Reset your password: <a href='{reset_link}'>{reset_link}</a></p>"
            f"<p>This link expires in {ttl} minutes.</p>"
            "<p>— The Neura team</p>"
        )
        txt = (
            "Hello,\n"
            f"Reset your password: {reset_link}\n"
            f"This link expires in {ttl} minutes.\n"
            "— The Neura team\n"
        )

    # Build with alias-aware validator (avoids 'from' kwarg problem)
    try:
        msg = _build_email_message(
            subject="Reset your password",
            from_addr=from_addr,
            to_email=to_email,
            html=html,
            txt=txt,
        )
    except Exception as e:
        log.exception("EmailMessage construction failed (reset): %s", e)
        raise

    log.info("[MAIL] sending password reset to %s from %s", to_email, from_addr.email)
    _dispatch(msg)

def send_email_verification(to_email: str, verify_link: str, expires_hours: int | None = None) -> None:
    """
    Email verification message.
    """
    from_addr = _resolve_from_addr()
    hrs = expires_hours or int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "24"))

    try:
        html, txt = render_template(
            "verify_email",
            user_name=to_email.split("@")[0],
            verify_url=verify_link,
            expires_hours=hrs,
        )
    except Exception as e:
        log.warning("render_template(verify_email) failed; using fallback: %s", e)
        html = (
            "<p>Hello,</p>"
            f"<p>Verify your email: <a href='{verify_link}'>{verify_link}</a></p>"
            f"<p>This link expires in {hrs} hours.</p>"
            "<p>— The Neura team</p>"
        )
        txt = (
            "Hello,\n"
            f"Verify your email: {verify_link}\n"
            f"This link expires in {hrs} hours.\n"
            "— The Neura team\n"
        )

    try:
        msg = _build_email_message(
            subject="Verify your email",
            from_addr=from_addr,
            to_email=to_email,
            html=html,
            txt=txt,
        )
    except Exception as e:
        log.exception("EmailMessage construction failed (verify): %s", e)
        raise

    log.info("[MAIL] sending verification to %s from %s", to_email, from_addr.email)
    _dispatch(msg)
