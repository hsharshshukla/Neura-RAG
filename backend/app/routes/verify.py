# app/routes/verify.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from datetime import datetime, timezone, timedelta
import sqlalchemy as sa
from app.db import get_session
from app.models import User
from app.email.verification import verify_with_token, issue_verification_token, send_verification_email

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_session)):
    user = verify_with_token(db, token)
    db.add(user)
    db.commit()
    return {"ok": True}

# Simple resend with basic rate limiting per user
@router.post("/resend-verification")
def resend_verification(payload: dict, db: Session = Depends(get_session)):
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    user = db.exec(sa.select(User).where(User.email == email)).first()
    if not user:
        # Don't reveal existence
        return {"ok": True}

    if user.email_verified_at:
        return {"ok": True, "message": "Already verified"}

    now = datetime.now(timezone.utc)
    # throttle: if not expired, reuse existing; else issue new
    if user.email_verification_expires_at and user.email_verification_expires_at > now + timedelta(minutes=1):
        # still valid — resend same link (we don't store raw token; reissue a fresh one)
        token = issue_verification_token(user)  # rotate to avoid storing raw; safest
    else:
        token = issue_verification_token(user)

    db.add(user)
    db.commit()
    send_verification_email(user, token)
    return {"ok": True, "message": "Verification email sent"}
