# app/email/service.py
from __future__ import annotations

import os
import asyncio
import logging
from typing import Optional, Callable, Awaitable, Tuple, List, Set
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.email.models import EmailMessage, EmailAddress, EmailSendResult
from app.email.providers.base import EmailProvider
from app.email.providers.smtp import SMTPProvider

log = logging.getLogger("email")

# Jinja2 environment for templates in app/email/templates/
_TPL_DIR = os.path.join(os.path.dirname(__file__), "templates")
_jinja = Environment(
    loader=FileSystemLoader(_TPL_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

def render_template(name: str, **ctx) -> Tuple[str, str]:
    """
    Render (html, text) for a template pair: <name>.html and <name>.txt
    Falls back to a naive HTML->text strip if .txt is absent.
    """
    html = _jinja.get_template(name + ".html").render(**ctx)
    try:
        txt = _jinja.get_template(name + ".txt").render(**ctx)
    except Exception:
        import re
        txt = re.sub(r"<[^>]+>", "", html)
    return html, txt

def _make_provider() -> EmailProvider:
    # SMTP-only; settings are env-driven inside SMTPProvider
    return SMTPProvider()

def _parse_allowlist(env_val: str | None) -> Set[str]:
    if not env_val:
        return set()
    return {e.strip().lower() for e in env_val.split(",") if e.strip()}

def _apply_nonprod_policies(msg: EmailMessage) -> Optional[EmailSendResult]:
    """
    Apply safety rails in non-prod:
      - subject prefix (EMAIL_SUBJECT_PREFIX or [ENV])
      - redirect all mail to a catchall (EMAIL_REDIRECT_TO), OR
      - filter by allowlist (EMAIL_ALLOWLIST)
    Returns an EmailSendResult if the send should be skipped; otherwise None.
    """
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "dev").strip().lower()
    is_prod = env in ("prod", "production")

    # Always tag environment header for observability
    msg.headers = dict(msg.headers or {})
    msg.headers.setdefault("X-App-Env", env)

    if is_prod:
        return None  # nothing else to do

    # Subject prefix
    prefix = os.getenv("EMAIL_SUBJECT_PREFIX") or f"[{env.upper()}] "
    if prefix and not (msg.subject or "").startswith(prefix):
        msg.subject = f"{prefix}{msg.subject}"

    # Recipient policies
    redirect = (os.getenv("EMAIL_REDIRECT_TO") or "").strip()
    allowlist = _parse_allowlist(os.getenv("EMAIL_ALLOWLIST"))

    if redirect:
        # Send all messages to a non-prod catchall
        msg.to = [EmailAddress(email=redirect)]
        msg.cc = []
        msg.bcc = []
        return None  # proceed with sending to the catchall

    if allowlist:
        def keep(lst: List[EmailAddress]) -> List[EmailAddress]:
            return [r for r in lst if r.email.lower() in allowlist]

        msg.to = keep(msg.to or [])
        msg.cc = keep(msg.cc or [])
        msg.bcc = keep(msg.bcc or [])

        if not (msg.to or msg.cc or msg.bcc):
            # Nothing allowed: skip send, report as queued/no-op
            log.info("[email] Non-prod allowlist removed all recipients; skipping send.")
            return EmailSendResult(
                provider="disabled",
                message_id=None,
                status="queued",
                raw={"reason": "no allowed recipients", "env": env},
            )

    return None  # proceed

class EmailService:
    """SMTP-only email service with retries and non-prod safety rails."""
    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max_attempts
        self.primary = _make_provider()
        self.disabled = os.getenv("DISABLE_EMAIL", "").lower() in ("1", "true", "yes")

    async def _with_retries(self, fn: Callable[[], Awaitable[EmailSendResult]]) -> EmailSendResult:
        delay = 0.5
        for i in range(self.max_attempts):
            try:
                return await fn()
            except Exception as e:
                if i == self.max_attempts - 1:
                    raise
                log.warning("Email send attempt %s failed: %s (retrying)", i + 1, e)
                await asyncio.sleep(delay)
                delay *= 2

    async def send(self, msg: EmailMessage) -> EmailSendResult:
        if self.disabled:
            log.info("[email] DISABLE_EMAIL=1 (pretend-sent)")
            return EmailSendResult(provider="disabled", message_id=None, status="queued")

        # Apply non-prod guards (prefix/allowlist/redirect)
        maybe_skip = _apply_nonprod_policies(msg)
        if maybe_skip is not None:
            return maybe_skip  # do not actually send

        # Send via SMTP with retries
        return await self._with_retries(lambda: self.primary.send(msg))

def make_default_service() -> EmailService:
    return EmailService()

def make_from_env(default_from: Optional[str] = None, default_name: Optional[str] = None) -> EmailAddress:
    """
    Resolve the default From address/name from env (or provided overrides).
    Required env: EMAIL_FROM_ADDRESS; optional: EMAIL_FROM_NAME
    """
    email = default_from or os.getenv("EMAIL_FROM_ADDRESS")
    name = default_name or os.getenv("EMAIL_FROM_NAME")
    if not email:
        raise RuntimeError("EMAIL_FROM_ADDRESS is not set")
    return EmailAddress(email=email, name=name)
