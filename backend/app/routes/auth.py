# app/routes/auth.py
# from __future__ import annotations

import os, hashlib, secrets, base64
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Depends, HTTPException, Request, Response, Cookie

from jose import jwt, JWTError
from pydantic import BaseModel, Field, EmailStr
from sqlmodel import Session, select
from sqlalchemy import text

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user
from app.utils.security import get_password_hash, verify_password
from app.utils.logger import log_event
from app.utils.mailer import send_email_verification

from app.rate_limit import  key_user_or_ip

# ---- config ----
LEGACY_VERIFY_CUTOFF = os.getenv("LEGACY_VERIFY_CUTOFF_ISO", "2025-08-24T00:00:00Z")
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "true").lower() in ("1","true","yes","on")

CURRENT_TOS_VERSION = os.getenv("TOS_VERSION", "2025-08-01")
CURRENT_PRIVACY_VERSION = os.getenv("PRIVACY_VERSION", "2025-08-01")

SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
ALGORITHM = os.getenv("JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRES_SECONDS", "86400"))

VERIFY_TOKEN_TTL_HOURS = int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "24"))
FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")

ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "access_token")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
COOKIE_PATH = "/"

CONSOLE_ENABLED_DEFAULT = os.getenv("CONSOLE_ENABLED_DEFAULT", "true").lower() in ("1","true","yes","on")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
alias = APIRouter(prefix="/api/v1", tags=["auth"])

# ---- helpers ----
def create_access_token(user: User, expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS) -> str:
    exp = datetime.utcnow() + timedelta(seconds=expires_in)
    ver = (getattr(user, "token_version", 0) or 0)
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
    response.delete_cookie(key=ACCESS_COOKIE_NAME, path=COOKIE_PATH, domain=COOKIE_DOMAIN)

def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def _sha256(s: str) -> str:
    h = hashlib.sha256(); h.update(s.encode("utf-8")); return h.hexdigest()

def _generate_verify_token() -> str:
    """
    Generate an email-safe verification token.
    Uses urlsafe base64 and strips padding.
    """
    raw = os.urandom(32)
    token = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return token


def _ensure_email_verify_table(db: Session) -> None:
    db.exec(text("""
        CREATE TABLE IF NOT EXISTS public.email_verify_token (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ
        );
    """))
    db.exec(text("CREATE INDEX IF NOT EXISTS idx_evt_user ON public.email_verify_token(user_id);"))
    db.exec(text("CREATE INDEX IF NOT EXISTS idx_evt_expires ON public.email_verify_token(expires_at);"))
    db.commit()

def _set_user_verified(user: User) -> None:
    now = datetime.now(timezone.utc)
    if hasattr(user, "email_verified"): user.email_verified = True
    if hasattr(user, "verified"): user.verified = True
    if hasattr(user, "email_verified_at"): user.email_verified_at = now
    if hasattr(user, "verified_at"): user.verified_at = now

def _is_verified(user: User) -> bool:
    return bool(getattr(user, "email_verified_at", None))

def _feature_flags(user: Optional[User]) -> dict:
    flags = {"console_enabled": bool(CONSOLE_ENABLED_DEFAULT)}
    if not user:
        return flags
    role = (getattr(user, "role", "") or "").lower()
    if role in {"owner", "admin", "support", "finance", "analyst", "readonly"}:
        flags["console_enabled"] = True
    return flags

# ---- models ----
class ChangePasswordIn(BaseModel):
    newPassword: str = Field(min_length=6, max_length=256)

class VerifyStartIn(BaseModel):
    email: EmailStr

class VerifyConfirmIn(BaseModel):
    token: str

# ---- routes ----

# @router.post("/signup")
# # @limiter.limit("6/minute; 60/hour")
# def signup(
#     request: Request,
#     response: Response,
#     email: str = Form(...),
#     password: str = Form(...),
#     name: Optional[str] = Form(None),
#     agree: bool = Form(False),
#     marketingOptIn: bool = Form(False),
#     tosVersion: Optional[str] = Form(None),
#     privacyVersion: Optional[str] = Form(None),
#     db: Session = Depends(get_session),
# ):
#     email_norm = email.strip().lower()

#     if not agree:
#         raise HTTPException(status_code=400, detail="You must accept the Terms & Privacy.")

#     if tosVersion != CURRENT_TOS_VERSION or privacyVersion != CURRENT_PRIVACY_VERSION:
#         raise HTTPException(status_code=400, detail="Legal version mismatch.")

#     existing = db.exec(select(User).where(User.email == email_norm)).first()
#     if existing:
#         raise HTTPException(status_code=400, detail="Email already registered")

#     now = datetime.utcnow()
#     user = User(
#         email=email_norm,
#         password=get_password_hash(password),
#         tier="free",
#         name=(name or email_norm.split("@")[0].capitalize()),
#         created_at=now,
#         token_version=0,
#         tos_version=CURRENT_TOS_VERSION,
#         privacy_version=CURRENT_PRIVACY_VERSION,
#         tos_accepted_at=now,
#         privacy_accepted_at=now,
#         marketing_opt_in=marketingOptIn,
#         consent_ip=client_ip(request),
#         consent_ua=request.headers.get("user-agent"),
#     )
#     db.add(user)
#     db.commit()
#     db.refresh(user)


#     # db.add(user); db.commit(); db.refresh(user)

#     # if REQUIRE_EMAIL_VERIFICATION:
#     #     _ensure_email_verify_table(db)
#     #     db.exec(text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()").bindparams(u=user.id))

#     #     raw = secrets.token_urlsafe(32)
#     #     tok_hash = _sha256(raw)
#     #     expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

#     #     db.exec(text("""
#     #         INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
#     #         VALUES (:u, :h, :e)
#     #     """).bindparams(u=user.id, h=tok_hash, e=expires))
#     #     db.commit()

#     #     link = f"{FRONTEND_URL}/verify?token={raw}"
#     #     send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)

#         # return {"ok": True, "verify_sent": True, "email": user.email}

#     if REQUIRE_EMAIL_VERIFICATION:
#         _ensure_email_verify_table(db)
#         db.exec(
#             text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()")
#             .bindparams(u=user.id)
#         )

#         token = _generate_verify_token()
#         tok_hash = _sha256(token)
#         expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

#         db.exec(text("""
#             INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
#             VALUES (:u, :h, :e)
#         """).bindparams(u=user.id, h=tok_hash, e=expires))
#         db.commit()

#         link = f"{FRONTEND_URL}/verify?token={token}"
#         send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)

#         return {"ok": True, "verify_sent": True, "email": user.email}


#     token = create_access_token(user)
#     set_auth_cookie(response, token)
#     return {"email": user.email, "tier": user.tier, "name": user.name}

# @router.post("/signup")
# def signup(
#     request: Request,
#     response: Response,
#     email: str = Form(...),
#     password: str = Form(...),
#     name: Optional[str] = Form(None),
#     agree: bool = Form(False),
#     marketingOptIn: bool = Form(False),
#     tosVersion: Optional[str] = Form(None),
#     privacyVersion: Optional[str] = Form(None),
#     db: Session = Depends(get_session),
# ):
#     email_norm = email.strip().lower()

#     if not agree:
#         raise HTTPException(status_code=400, detail="You must accept the Terms & Privacy.")

#     if tosVersion != CURRENT_TOS_VERSION or privacyVersion != CURRENT_PRIVACY_VERSION:
#         raise HTTPException(status_code=400, detail="Legal version mismatch.")

#     existing = db.exec(select(User).where(User.email == email_norm)).first()
#     if existing:
#         raise HTTPException(status_code=400, detail="Email already registered")

#     now = datetime.utcnow()
#     user = User(
#         email=email_norm,
#         password=get_password_hash(password),
#         tier="free",
#         name=(name or email_norm.split("@")[0].capitalize()),
#         created_at=now,
#         token_version=0,
#         tos_version=CURRENT_TOS_VERSION,
#         privacy_version=CURRENT_PRIVACY_VERSION,
#         tos_accepted_at=now,
#         privacy_accepted_at=now,
#         marketing_opt_in=marketingOptIn,
#         consent_ip=client_ip(request),
#         consent_ua=request.headers.get("user-agent"),
#     )

#     # SAVE USER FIRST
#     db.add(user)
#     db.commit()
#     db.refresh(user)

#     # NOW create verification token
#     if REQUIRE_EMAIL_VERIFICATION:
#         _ensure_email_verify_table(db)

#         db.exec(
#             text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()")
#             .bindparams(u=user.id)
#         )

#         token = _generate_verify_token()
#         tok_hash = _sha256(token)
#         expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

#         db.exec(text("""
#             INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
#             VALUES (:u, :h, :e)
#         """).bindparams(u=user.id, h=tok_hash, e=expires))
#         db.commit()

#         link = f"{FRONTEND_URL}/verify?token={token}"
#         send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)

#         return {"ok": True, "verify_sent": True, "email": user.email}

#     token = create_access_token(user)
#     set_auth_cookie(response, token)
#     return {"email": user.email, "tier": user.tier, "name": user.name}

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
    email_norm = email.strip().lower()

    if not agree:
        raise HTTPException(status_code=400, detail="You must accept the Terms & Privacy.")

    if tosVersion != CURRENT_TOS_VERSION or privacyVersion != CURRENT_PRIVACY_VERSION:
        raise HTTPException(status_code=400, detail="Legal version mismatch.")

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
        marketing_opt_in=marketingOptIn,
        consent_ip=client_ip(request),
        consent_ua=request.headers.get("user-agent"),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    if REQUIRE_EMAIL_VERIFICATION:
        _ensure_email_verify_table(db)

        db.exec(
            text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()")
            .bindparams(u=user.id)
        )

        token = _generate_verify_token()
        tok_hash = _sha256(token)
        expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

        db.exec(text("""
            INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
            VALUES (:u, :h, :e)
        """).bindparams(u=user.id, h=tok_hash, e=expires))
        db.commit()

        link = f"{FRONTEND_URL}/verify?token={token}"
        send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)

        return {"ok": True, "verify_sent": True, "email": user.email}

    token = create_access_token(user)
    set_auth_cookie(response, token)
    return {"email": user.email, "tier": user.tier, "name": user.name}


@router.post("/login")
# @limiter.limit("12/minute; 120/hour")
def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    email_norm = email.strip().lower()
    user = db.exec(select(User).where(User.email == email_norm)).first()

    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # if REQUIRE_EMAIL_VERIFICATION and not _is_verified(user):
    #     raise HTTPException(status_code=403, detail="Email not verified")

    if REQUIRE_EMAIL_VERIFICATION and not _is_verified(user):
        _ensure_email_verify_table(db)

        db.exec(
            text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()")
            .bindparams(u=user.id)
        )

        token = _generate_verify_token()
        tok_hash = _sha256(token)
        expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

        db.exec(text("""
            INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
            VALUES (:u, :h, :e)
        """).bindparams(u=user.id, h=tok_hash, e=expires))
        db.commit()

        link = f"{FRONTEND_URL}/verify?token={token}"
        send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)

        raise HTTPException(
            status_code=403,
            detail="Email not verified. A new verification link was sent."
        )

    
    token = create_access_token(user)
    set_auth_cookie(response, token)
    return {
        "email": user.email,
        "tier": user.tier,
        "name": user.name,
        "role": getattr(user, "role", "user"),
        "access_token": token,
    }

@router.post("/logout")
# @limiter.limit("30/minute")
def logout(request: Request, response: Response):
    clear_auth_cookie(response)
    return {"ok": True}

@router.post("/change-password")
# @limiter.limit("6/minute; 60/hour", key_func=key_user_or_ip)
def change_password(
    request: Request,
    response: Response,
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
# @limiter.limit("3/minute; 30/hour", key_func=key_user_or_ip)
def logout_all(
    request: Request,
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email.lower())).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.token_version += 1
    db.add(user); db.commit()
    clear_auth_cookie(response)
    return {"ok": True}

@router.post("/accept-terms")
# @limiter.limit("20/minute", key_func=key_user_or_ip)
def accept_terms(
    request: Request,
    response: Response,
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

    return {"ok": True}

@router.post("/verify/start", status_code=204)
# @limiter.limit("3/minute; 30/hour")
def verify_start(
    request: Request,
    response: Response,
    body: VerifyStartIn,
    db: Session = Depends(get_session),
):
    _ensure_email_verify_table(db)

    email_norm = body.email.strip().lower()
    user = db.exec(select(User).where(User.email == email_norm)).first()

    if not user or _is_verified(user):
        return

    # db.exec(text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()").bindparams(u=user.id))
    # raw = secrets.token_urlsafe(32)
    # tok_hash = _sha256(raw)
    # expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

    # db.exec(text("""
    #     INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
    #     VALUES (:u, :h, :e)
    # """).bindparams(u=user.id, h=tok_hash, e=expires))
    # db.commit()

    # link = f"{FRONTEND_URL}/verify?token={raw}"
    # send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)
    # return
    db.exec(
        text("DELETE FROM public.email_verify_token WHERE user_id=:u OR expires_at<NOW()")
        .bindparams(u=user.id)
    )

    token = _generate_verify_token()
    tok_hash = _sha256(token)
    expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)

    db.exec(text("""
        INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
        VALUES (:u, :h, :e)
    """).bindparams(u=user.id, h=tok_hash, e=expires))
    db.commit()

    link = f"{FRONTEND_URL}/verify?token={token}"
    send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)
    return


@router.post("/verify/confirm")
# @limiter.limit("12/minute; 120/hour")
def verify_confirm(
    request: Request,
    response: Response,
    payload: VerifyConfirmIn,
    db: Session = Depends(get_session),
):
    # _ensure_email_verify_table(db)
    # tok_hash = _sha256(payload.token)
    _ensure_email_verify_table(db)
    token = payload.token.strip()
    tok_hash = _sha256(token)

    rec = db.exec(text("""
        SELECT id, user_id
        FROM public.email_verify_token
        WHERE token_hash=:h AND used_at IS NULL AND expires_at > NOW()
        LIMIT 1
    """).bindparams(h=tok_hash)).mappings().first()

    if not rec:
        raise HTTPException(status_code=400, detail="Invalid/expired token")

    user = db.exec(select(User).where(User.id == rec["user_id"])).first()

    _set_user_verified(user)
    db.add(user)
    db.exec(text("UPDATE public.email_verify_token SET used_at=NOW() WHERE id=:i").bindparams(i=rec["id"]))
    db.commit()

    return {"ok": True}

@router.post("/resend-verification", status_code=204)
def resend_verification(
    request: Request,
    response: Response,
    body: VerifyStartIn,
    db: Session = Depends(get_session),
):
    return verify_start(request=request, response=response, body=body, db=db)

@router.get("/verify-email")
def verify_email(
    request: Request,
    response: Response,
    token: str,
    db: Session = Depends(get_session),
):
    return verify_confirm(
        request=request,
        response=response,
        payload=VerifyConfirmIn(token=token),
        db=db
    )

@router.get("/me")
def soft_me(
    request: Request,
    response: Response,
    access_token: Optional[str] = Cookie(None, alias=ACCESS_COOKIE_NAME),
    db: Session = Depends(get_session),
):
    if not access_token:
        return {"authenticated": False}

    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
    except:
        return {"authenticated": False}

    email = payload.get("sub", "").lower()
    ver = int(payload.get("ver", 0))

    user = db.exec(select(User).where(User.email == email)).first()

    if not user or int(user.token_version) != ver:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "email": user.email,
        "role": getattr(user, "role", "user"),
        "tier": user.tier,
        "name": user.name,
        "featureFlags": _feature_flags(user),
    }

@router.get("/whoami")
def whoami(
    request: Request,
    response: Response,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    return {
        "email": user.email,
        "role": getattr(user, "role", "user"),
        "tier": user.tier,
        "name": user.name,
    }

@alias.get("/me")
def soft_me_alias(
    request: Request,
    response: Response,
    access_token: Optional[str] = Cookie(None, alias=ACCESS_COOKIE_NAME),
    db: Session = Depends(get_session),
):
    return soft_me(request, response, access_token, db)
