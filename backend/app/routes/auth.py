# app/routes/auth.py
from fastapi import APIRouter, Form, Depends, HTTPException, Request, Response, status, Cookie
from sqlmodel import Session, select
from jose import jwt, JWTError
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional
import os

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user
from app.utils.security import get_password_hash, verify_password
from app.utils.logger import log_event

# ---- config ----
CURRENT_TOS_VERSION = os.getenv("TOS_VERSION", "2025-08-01")
CURRENT_PRIVACY_VERSION = os.getenv("PRIVACY_VERSION", "2025-08-01")

SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
ALGORITHM = os.getenv("JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRES_SECONDS", "86400"))

# Cookie settings (dev-friendly defaults)
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "access_token")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None     # e.g. "example.com" in prod
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"  # false for http://127.0.0.1
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # 'lax' | 'strict' | 'none'
COOKIE_PATH = "/"

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ---- helpers ----
def create_access_token(user: User, expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS) -> str:
    exp = datetime.utcnow() + timedelta(seconds=expires_in)
    ver = (user.token_version or 0)
    payload = {"sub": user.email, "ver": ver, "exp": exp}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_SECONDS,
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
    )

def clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
    )

def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ---- models ----
class ChangePasswordIn(BaseModel):
    newPassword: str = Field(min_length=6, max_length=256)

# ---- routes ----

@router.post("/signup")
def signup(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    name: Optional[str] = Form(None),
    agree: bool = Form(False),
    marketingOptIn: bool = Form(False),
    tosVersion: Optional[str] = Form(None),
    privacyVersion: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    email_norm = (email or "").strip().lower()
    if not agree:
        raise HTTPException(status_code=400, detail="You must accept the Terms & Privacy to create an account.")
    if tosVersion != CURRENT_TOS_VERSION or privacyVersion != CURRENT_PRIVACY_VERSION:
        raise HTTPException(status_code=400, detail="Legal version mismatch. Please refresh and try again.")

    existing = db.exec(select(User).where(User.email == email_norm)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    now = datetime.utcnow()
    user = User(
        email=email_norm,
        password=get_password_hash(password),
        tier="free",
        name=(name or email_norm.split("@")[0].capitalize()),
        created_at=now,
        token_version=0,
        tos_version=CURRENT_TOS_VERSION,
        privacy_version=CURRENT_PRIVACY_VERSION,
        tos_accepted_at=now,
        privacy_accepted_at=now,
        marketing_opt_in=bool(marketingOptIn),
        consent_ip=client_ip(request),
        consent_ua=request.headers.get("user-agent"),
    )
    db.add(user); db.commit(); db.refresh(user)

    log_event("CONSENT_RECORDED", {
        "email": user.email,
        "ip": user.consent_ip,
        "ua": user.consent_ua,
        "tos_version": user.tos_version,
        "privacy_version": user.privacy_version,
        "at": now.isoformat() + "Z",
    })

    token = create_access_token(user)
    set_auth_cookie(response, token)
    return {"email": user.email, "tier": user.tier, "name": user.name or "", "role": getattr(user, "role", "user")}

@router.post("/login")
def login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session)
):
    email_norm = (email or "").strip().lower()
    user = db.exec(select(User).where(User.email == email_norm)).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    needs_reconsent = (
        (user.tos_version or "") != CURRENT_TOS_VERSION
        or (user.privacy_version or "") != CURRENT_PRIVACY_VERSION
    )

    token = create_access_token(user)
    set_auth_cookie(response, token)
    return {
        "email": user.email,
        "tier": user.tier,
        "name": user.name or "",
        "role": getattr(user, "role", "user"),
        "needs_reconsent": needs_reconsent,
    }

@router.post("/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"ok": True}

@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email.lower())).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.password = get_password_hash(payload.newPassword)
    user.token_version = (user.token_version or 0) + 1
    db.add(user); db.commit()
    return {"ok": True}

@router.post("/logout-all")
def logout_all(
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email.lower())).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.token_version = (user.token_version or 0) + 1
    db.add(user); db.commit()
    clear_auth_cookie(response)
    return {"ok": True}

@router.post("/accept-terms")
def accept_terms(
    request: Request,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email.lower())).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    now = datetime.utcnow()
    user.tos_version = CURRENT_TOS_VERSION
    user.privacy_version = CURRENT_PRIVACY_VERSION
    user.tos_accepted_at = now
    user.privacy_accepted_at = now
    user.consent_ip = client_ip(request)
    user.consent_ua = request.headers.get("user-agent")
    db.add(user); db.commit()

    log_event("CONSENT_RENEWED", {
        "email": user.email,
        "ip": user.consent_ip,
        "ua": user.consent_ua,
        "tos_version": user.tos_version,
        "privacy_version": user.privacy_version,
        "at": now.isoformat() + "Z",
    })

    return {"ok": True}

# ✅ Soft session probe for the FE (never 401)
@router.get("/me")
def me(
    access_token: Optional[str] = Cookie(None, alias=ACCESS_COOKIE_NAME),
    db: Session = Depends(get_session),
):
    if not access_token:
        return {"authenticated": False}

    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return {"authenticated": False}

    email = (payload.get("sub") or "").lower()
    ver = int(payload.get("ver", 0))
    if not email:
        return {"authenticated": False}

    user = db.exec(select(User).where(User.email == email)).first()
    if not user or int(user.token_version or 0) != ver:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "email": user.email,
        "role": getattr(user, "role", "user"),
        "tier": user.tier,
        "name": user.name or "",
    }

# Legacy helper (still hard-auth)
@router.get("/whoami")
def whoami(user_email: str = Depends(get_current_user), db: Session = Depends(get_session)):
    user = db.exec(select(User).where(User.email == user_email)).first()
    return {"email": user.email, "role": getattr(user, "role", "user"), "tier": user.tier, "name": user.name or ""}
