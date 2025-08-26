from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlmodel import Session, select
from pydantic import BaseModel, EmailStr
import os

from app.db import get_session
from app.models import User, PasswordResetToken
from app.utils.password_reset import generate_raw_token, hash_token, ensure_not_expired
from app.utils.mailer import send_password_reset_email

router = APIRouter(prefix="/api/v1/auth/password", tags=["auth"])

# Use your existing FRONTEND_URL env to build the link
FRONTEND_BASE = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")

class ForgotIn(BaseModel):
    email: EmailStr

@router.post("/forgot", status_code=204)
def forgot_password(payload: ForgotIn, db: Session = Depends(get_session), request: Request = None):
    # Always 204 to avoid user enumeration
    user = db.exec(select(User).where(User.email == payload.email)).first()
    if user:
        raw = generate_raw_token()
        token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=PasswordResetToken.default_expiry(30),
        )
        db.add(token); db.commit()
        link = f"{FRONTEND_BASE}/reset?token={raw}"
        print(f"[forgot] issuing reset token for {user.email} -> {link}")

        send_password_reset_email(user.email, link)
    return

class ResetIn(BaseModel):
    token: str
    new_password: str

@router.post("/reset", status_code=204)
def reset_password(body: ResetIn, db: Session = Depends(get_session)):
    token_hash = hash_token(body.token)
    rec = db.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False
        )
    ).first()

    if not rec:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    ensure_not_expired(rec.expires_at)

    user = db.exec(select(User).where(User.id == rec.user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    # ⬇️ (Your Q4) WHERE to plug hashing:
    # Reuse the SAME helper you use in your Settings change‑password flow.
    # If your code exposes User.hash_password, use it:
    if hasattr(User, "hash_password"):
        user.password = User.hash_password(body.new_password)
    else:
        # Fallback (only if you truly don't have a helper). Replace with your existing bcrypt/passlib.
        import bcrypt
        user.password = bcrypt.hashpw(body.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    rec.used = True
    db.add(user); db.add(rec); db.commit()
    return
