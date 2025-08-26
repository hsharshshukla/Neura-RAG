# app/email/providers/smtp.py
from __future__ import annotations

import os
from aiosmtplib.errors import (
    SMTPRecipientsRefused,
    SMTPDataError,
    SMTPResponseException,
    SMTPException,
)


from typing import Optional, List
from email.message import EmailMessage as StdEmailMessage
from email.utils import formataddr, make_msgid, formatdate
import aiosmtplib

from app.email.models import EmailMessage, EmailSendResult
from app.email.providers.base import EmailProvider


def _bool(env: str, default: bool = False) -> bool:
    v = os.getenv(env)
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


class SMTPProvider(EmailProvider):
    """
    Generic SMTP sender (Zoho, Gmail/Workspace, Outlook, SES-SMTP, Resend SMTP, Postmark SMTP, etc.)
    Reads settings from env by default:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TLS (STARTTLS), SMTP_SSL (implicit TLS), SMTP_TIMEOUT
    """
    name = "smtp"

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        starttls: Optional[bool] = None,
        use_ssl: Optional[bool] = None,
        timeout: Optional[int] = None,
    ):
        # Config (env-driven by default)
        self.host = (host or os.getenv("SMTP_HOST") or "localhost").strip()
        self.port = int(port or os.getenv("SMTP_PORT", "587"))
        self.user = (username or os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME") or "").strip()
        self.password = (password or os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD") or "").strip()
        self.use_ssl = bool(use_ssl if use_ssl is not None else _bool("SMTP_SSL", False))     # implicit TLS on 465
        self.starttls = bool(starttls if starttls is not None else _bool("SMTP_TLS", True))   # STARTTLS on 587
        self.timeout = int(timeout or os.getenv("SMTP_TIMEOUT", "15"))

    async def send(self, msg: EmailMessage) -> EmailSendResult:
        # Validate recipients
        if not msg.to or len(msg.to) == 0:
            raise ValueError("EmailMessage.to must contain at least one recipient")

        # Build RFC-compliant email
        em = StdEmailMessage()
        em["From"] = formataddr((msg.from_.name or "", msg.from_.email))
        em["To"] = ", ".join(formataddr((x.name or "", x.email)) for x in msg.to)
        if msg.cc:
            em["Cc"] = ", ".join(formataddr((x.name or "", x.email)) for x in msg.cc)
        if msg.reply_to:
            em["Reply-To"] = formataddr((msg.reply_to.name or "", msg.reply_to.email))
        for k, v in (msg.headers or {}).items():
            # Allow provider-specific headers (e.g., Postmark X-PM-*, SES configuration-set, etc.)
            em[k] = str(v)

        em["Subject"] = msg.subject
        em["Date"] = formatdate(localtime=True)
        if "Message-ID" not in em:
            em["Message-ID"] = make_msgid(domain=self.host)

        # Body: multipart/alternative if both text & html provided
        text = (msg.text or "").strip() if msg.text else None
        html = (msg.html or "").strip() if msg.html else None

        if text and html:
            em.set_content(text)
            em.add_alternative(html, subtype="html")
        elif text:
            em.set_content(text)
        elif html:
            em.set_content(html, subtype="html")
        else:
            em.set_content("")  # empty but valid message

        # Attachments
        for att in msg.attachments or []:
            ctype = att.content_type or "application/octet-stream"
            if "/" in ctype:
                maintype, subtype = ctype.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"
            em.add_attachment(att.content, maintype=maintype, subtype=subtype, filename=att.filename)

        # Send via SMTP
        smtp = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            use_tls=self.use_ssl,  # implicit TLS (e.g., 465)
            timeout=self.timeout,
        )

        # Envelope recipients include BCC (not present in headers)
        recipients: List[str] = [x.email for x in msg.to] + [x.email for x in msg.cc] + [x.email for x in msg.bcc]
        sender = msg.from_.email
        try:
            await smtp.connect()

            # Opportunistic STARTTLS if configured and not already using implicit TLS
            if self.starttls and not self.use_ssl:
                try:
                    if not getattr(smtp, "is_tls", False):
                        await smtp.starttls()
                except SMTPException as e:
                    # Ignore "already using TLS", re-raise others
                    if "already using tls" not in str(e).lower():
                        raise

            if self.user and self.password:
                await smtp.login(self.user, self.password)

            # ---- verbose error handling for the DATA/send stage ----
            try:
                resp = await smtp.send_message(em, sender=sender, recipients=recipients or None)
            except SMTPRecipientsRefused as e:
                # {recipient: (code, message)}
                raise RuntimeError(f"SMTP recipients refused: {e.recipients}") from e
            except SMTPDataError as e:
                raise RuntimeError(f"SMTP data error {e.code}: {e.message}") from e
            except SMTPResponseException as e:
                raise RuntimeError(f"SMTP response {e.code}: {e.message}") from e

        except Exception as e:
            # Normalize error for callers (connect/login/etc. failures)
            raise RuntimeError(f"SMTP send failed: {type(e).__name__}: {e}") from e
        finally:
            try:
                await smtp.quit()
            except Exception:
                pass


        # try:
        #     await smtp.connect()

        #     # Opportunistic STARTTLS if configured and not already using implicit TLS
        #     # AFTER (more robust)
        #     if self.starttls and not self.use_ssl:
        #         try:
        #             # Only upgrade if not already over TLS
        #             if not getattr(smtp, "is_tls", False):
        #                 await smtp.starttls()
        #         except aiosmtplib.errors.SMTPException as e:
        #             # Ignore "already using TLS", re-raise others
        #             if "already using tls" not in str(e).lower():
        #                 raise


        #     if self.user and self.password:
        #         await smtp.login(self.user, self.password)

        #     resp = await smtp.send_message(em, sender=sender, recipients=recipients or None)
        # except Exception as e:
        #     # Normalize error message for callers
        #     raise RuntimeError(f"SMTP send failed: {e}") from e
        # finally:
        #     try:
        #         await smtp.quit()
        #     except Exception:
        #         # Connection might already be closed; ignore
        #         pass

        first_rcpt = next(iter(resp)) if isinstance(resp, dict) and resp else None
        return EmailSendResult(
            provider=self.name,
            message_id=str(em["Message-ID"]),
            status="sent",
            raw={"smtp": resp, "first_rcpt": first_rcpt},
        )
