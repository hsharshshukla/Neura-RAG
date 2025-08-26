# app/email/verification.py
from __future__ import annotations
import os, secrets, hashlib, hmac
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlmodel import Session
from app.models import User
from app.email.service import make_default_service, render_template, make_from_env  # your existing mail infra

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def issue_verification_token(user: User, ttl_hours: int = 24) -> str:
    raw = secrets.token_urlsafe(48)  # send to user
    user.email_verification_token_hash = _hash_token(raw)
    user.email_verification_expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    return raw

def send_verification_email(user: User, token: str):
    base_url = os.getenv("APP_PUBLIC_URL", "http://localhost:3000")
    verify_url = f"{base_url}/verify?token={token}"
    svc = make_default_service()
    frm = make_from_env()

    try:
        html, txt = render_template("verify_email", user_name=user.name or user.email.split("@")[0], verify_url=verify_url)
    except Exception:
        html = f"<p>Hi {user.name or ''},</p><p>Verify your email by clicking <a href='{verify_url}'>this link</a>.</p>"
        txt = f"Verify your email: {verify_url}"

    # DEV helper
    if str(os.getenv("DEV_EMAIL_LOG_ONLY", "false")).lower() in ("1","true","yes","on"):
        print(f"[DEV MAIL] Verification link for {user.email}: {verify_url}")
        return

    svc.send(frm, to=[user.email], subject="Verify your email", html=html, text=txt)

def verify_with_token(db: Session, token: str) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    user = db.exec(
        # SQLModel style — adjust if you use pure SA
        sa.select(User).where(User.email_verification_token_hash == token_hash)
    ).first() if hasattr(db, "exec") else None

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token not found")

    now = datetime.now(timezone.utc)
    if not user.email_verification_expires_at or user.email_verification_expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token expired")

    user.email_verified_at = now
    user.email_verification_token_hash = None
    user.email_verification_expires_at = None
    return user
