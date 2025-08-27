# app/routes/auth.py
from fastapi import APIRouter, Form, Depends, HTTPException, Request, Response, Cookie, status, BackgroundTasks
from sqlmodel import Session, select
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
import os, hashlib, secrets
from sqlalchemy import text

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user
from app.utils.security import get_password_hash, verify_password
from app.utils.logger import log_event
from app.utils.mailer import send_email_verification
from datetime import datetime, timezone
LEGACY_VERIFY_CUTOFF = os.getenv("LEGACY_VERIFY_CUTOFF_ISO", "2025-08-24T00:00:00Z")
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "true").lower() in ("1","true","yes","on")

# ---- config ----
CURRENT_TOS_VERSION = os.getenv("TOS_VERSION", "2025-08-01")
CURRENT_PRIVACY_VERSION = os.getenv("PRIVACY_VERSION", "2025-08-01")

SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
ALGORITHM = os.getenv("JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRES_SECONDS", "86400"))

# Email verification
VERIFY_TOKEN_TTL_HOURS = int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "24"))
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "true").lower() in ("1", "true", "yes", "on")
FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")

# Cookie settings (dev-friendly defaults)
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "access_token")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
COOKIE_PATH = "/"

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
alias = APIRouter(prefix="/api/v1", tags=["auth"])  # Soft alias for /api/v1/me

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
    if hasattr(user, "email_verified"):
        setattr(user, "email_verified", True)
    if hasattr(user, "verified"):
        setattr(user, "verified", True)
    now = datetime.now(timezone.utc)
    if hasattr(user, "email_verified_at"):
        setattr(user, "email_verified_at", now)
    if hasattr(user, "verified_at"):
        setattr(user, "verified_at", now)

# def _is_verified(user: User) -> bool:
#     return bool(
#         getattr(user, "email_verified_at", None)  # current field
#         or getattr(user, "verified_at", None)    # future/alt
#         or getattr(user, "verified", False)
#         or getattr(user, "email_verified", False)
#     )
def _is_verified(user: User) -> bool:
    # Strict: only accept the canonical field we write on confirm/backfill
    return bool(getattr(user, "email_verified_at", None))
    


# ---- models ----
class ChangePasswordIn(BaseModel):
    newPassword: str = Field(min_length=6, max_length=256)

class VerifyStartIn(BaseModel):
    email: EmailStr

class VerifyConfirmIn(BaseModel):
    token: str

# ---- routes (authn) ----

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
    background: BackgroundTasks = None,
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
        password=get_password_hash(password),  # model uses `password` field
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

    # Send verification on signup
    if REQUIRE_EMAIL_VERIFICATION:
        _ensure_email_verify_table(db)
        # Clean old tokens for this user and expired ones
        db.exec(text("DELETE FROM public.email_verify_token WHERE user_id = :u OR expires_at < NOW()").bindparams(u=user.id))
        raw = secrets.token_urlsafe(32)
        tok_hash = _sha256(raw)
        expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)
        db.exec(text("""
            INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
            VALUES (:u, :h, :e)
        """).bindparams(u=user.id, h=tok_hash, e=expires))
        db.commit()

        link = f"{FRONTEND_URL}/verify?token={raw}"
        if background:
            background.add_task(send_email_verification, user.email, link, VERIFY_TOKEN_TTL_HOURS)
        else:
            send_email_verification(user.email, link, VERIFY_TOKEN_TTL_HOURS)

        # Do NOT log the user in yet
        return {"ok": True, "verify_sent": True, "email": user.email}

    # If verification is optional in this environment, proceed with auto-login
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

    # Block unverified users if required
    if REQUIRE_EMAIL_VERIFICATION and not _is_verified(user):
    # if REQUIRE_EMAIL_VERIFICATION and not getattr(user, "email_verified_at", None):
        print("LOGIN_BLOCKED", {
        "email": user.email,
        "created_at": str(getattr(user, "created_at", None)),
        "email_verified_at": str(getattr(user, "email_verified_at", None)),
        })
        raise HTTPException(status_code=403, detail="Email not verified")

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
        "access_token": token,  # optional for legacy clients
        "token_type": "bearer",
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

# ---------- Email verification endpoints ----------

@router.post("/verify/start", status_code=204)
def verify_start(
    body: VerifyStartIn,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
):
    """
    Always 204 (avoid user enumeration). If user exists and unverified, send a link.
    """
    _ensure_email_verify_table(db)
    email_norm = str(body.email).strip().lower()
    user = db.exec(select(User).where(User.email == email_norm)).first()
    if not user or _is_verified(user):
        return

    # Cleanup and issue a new token
    db.exec(text("DELETE FROM public.email_verify_token WHERE user_id = :u OR expires_at < NOW()")
            .bindparams(u=user.id))
    raw = secrets.token_urlsafe(32)
    tok_hash = _sha256(raw)
    expires = datetime.utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS)
    db.exec(text("""
        INSERT INTO public.email_verify_token (user_id, token_hash, expires_at)
        VALUES (:u, :h, :e)
    """).bindparams(u=user.id, h=tok_hash, e=expires))
    db.commit()

    link = f"{FRONTEND_URL}/verify?token={raw}"
    background.add_task(send_email_verification, user.email, link, VERIFY_TOKEN_TTL_HOURS)
    return

@router.post("/verify/confirm")
def verify_confirm(
    payload: VerifyConfirmIn,
    db: Session = Depends(get_session),
):
    _ensure_email_verify_table(db)
    tok_hash = _sha256(payload.token)

    # Validate in SQL to avoid tz pitfalls
    rec = db.exec(text("""
        SELECT id, user_id
        FROM public.email_verify_token
        WHERE token_hash = :h
          AND used_at IS NULL
          AND expires_at > NOW()
        LIMIT 1
    """).bindparams(h=tok_hash)).mappings().first()

    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.exec(select(User).where(User.id == rec["user_id"])).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid token")

    _set_user_verified(user)
    db.add(user)
    db.exec(text("UPDATE public.email_verify_token SET used_at = NOW() WHERE id = :i")
            .bindparams(i=rec["id"]))
    db.commit()
    return {"ok": True}

# ---- Compatibility aliases (keep UI flexible) ----

@router.post("/resend-verification", status_code=204)
def resend_verification(body: VerifyStartIn, background: BackgroundTasks, db: Session = Depends(get_session)):
    # Alias of /verify/start to support older clients
    return verify_start(body, background, db)

@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_session)):
    # Alias that accepts token via query param (GET) for older clients
    return verify_confirm(VerifyConfirmIn(token=token), db)

# ---------- Soft session probe (never 401) ----------

@router.get("/me")
def soft_me(
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

# ---------- Strict identity (401 if not logged in) ----------

@router.get("/whoami")
def whoami(user_email: str = Depends(get_current_user), db: Session = Depends(get_session)):
    user = db.exec(select(User).where(User.email == user_email)).first()
    return {"email": user.email, "role": getattr(user, "role", "user"), "tier": user.tier, "name": user.name or ""}

# ---------- Soft alias at /api/v1/me ----------

@alias.get("/me")
def soft_me_alias(
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
