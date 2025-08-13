from fastapi import APIRouter, Form, Depends, HTTPException, Request
from sqlmodel import Session, select
from jose import jwt
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

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ---- helpers ----
def create_access_token(user: User, expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS) -> str:
    exp = datetime.utcnow() + timedelta(seconds=expires_in)
    ver = (user.token_version or 0)
    payload = {"sub": user.email, "ver": ver, "exp": exp}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

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
    email: str = Form(...),
    password: str = Form(...),
    name: Optional[str] = Form(None),
    agree: bool = Form(False),
    marketingOptIn: bool = Form(False),
    tosVersion: Optional[str] = Form(None),
    privacyVersion: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    # normalize
    email_norm = (email or "").strip().lower()

    if not agree:
        raise HTTPException(status_code=400, detail="You must accept the Terms & Privacy to create an account.")

    # prevent spoofing by requiring exact server versions
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
        privacy_accepted_at=now,              # ⬅️ stamp privacy as well
        marketing_opt_in=bool(marketingOptIn),
        consent_ip=client_ip(request),
        consent_ua=request.headers.get("user-agent"),
    )
    db.add(user); db.commit(); db.refresh(user)

    # audit log
    log_event("CONSENT_RECORDED", {
        "email": user.email,
        "ip": user.consent_ip,
        "ua": user.consent_ua,
        "tos_version": user.tos_version,
        "privacy_version": user.privacy_version,
        "at": now.isoformat() + "Z",
    })

    token = create_access_token(user)
    return {"email": user.email, "tier": user.tier, "name": user.name or "", "access_token": token}

@router.post("/login")
def login(
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
    return {
        "email": user.email,
        "tier": user.tier,
        "name": user.name or "",
        "access_token": token,
        "needs_reconsent": needs_reconsent,
    }

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
    user.token_version = (user.token_version or 0) + 1  # revoke all tokens
    db.add(user); db.commit()
    return {"ok": True}

@router.post("/logout-all")
def logout_all(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email.lower())).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.token_version = (user.token_version or 0) + 1
    db.add(user); db.commit()
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


# from fastapi import APIRouter, Form, Depends, HTTPException
# from sqlmodel import Session, select
# from app.models import User
# from app.db import get_session
# from jose import jwt
# from datetime import datetime, timedelta
# # from passlib.context import CryptContext
# from pydantic import BaseModel, Field
# from app.deps.auth import get_current_user  # ✅ use your dependency
# from app.utils.security import get_password_hash, verify_password
# from fastapi import APIRouter, Form, Depends, HTTPException, Request
# from app.utils.security import get_password_hash, verify_password  
# import os


# CURRENT_TOS_VERSION = os.getenv("TOS_VERSION", "2025-08-01")
# CURRENT_PRIVACY_VERSION = os.getenv("PRIVACY_VERSION", "2025-08-01")

# router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
# ALGORITHM = os.getenv("JWT_ALG", "HS256")
# ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRES_SECONDS", "86400"))


# # ----- helpers -----

# def create_access_token(user: User, expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS) -> str:
#     from datetime import datetime, timedelta
#     exp = datetime.utcnow() + timedelta(seconds=expires_in)
#     ver = getattr(user, "token_version", 0) or 0
#     payload = {"sub": user.email, "ver": ver, "exp": exp}
#     return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# # ----- models -----
# class ChangePasswordIn(BaseModel):
#     newPassword: str = Field(min_length=6, max_length=256)

# # ----- routes -----

# # ✅ REGISTER
# # @router.post("/signup")
# # def signup(
# #     email: str = Form(...),
# #     password: str = Form(...),
# #     name: str = Form(None),
# #     db: Session = Depends(get_session)
# # ):
# #     existing = db.exec(select(User).where(User.email == email)).first()
# #     if existing:
# #         raise HTTPException(status_code=400, detail="Email already registered")

# #     # hashed_password = pwd_context.hash(password)
# #     hashed_password = get_password_hash(password)   # ← put this here

    
# #     user = User(
# #         email=email,
# #         password=hashed_password,
# #         tier="free",
# #         name=name or email.split("@")[0].capitalize(),
# #         created_at=datetime.utcnow(),   # token_version defaults to 0
# #     )
# #     db.add(user)
# #     db.commit()
# #     db.refresh(user)

# #     token = create_access_token(user)
# #     return {"email": user.email, "tier": user.tier, "name": user.name or "", "access_token": token}
# @router.post("/signup")
# def signup(
#     request: Request,
#     email: str = Form(...),
#     password: str = Form(...),
#     name: str = Form(None),
#     agree: bool = Form(False),
#     marketingOptIn: bool = Form(False),
#     tosVersion: str = Form(None),
#     privacyVersion: str = Form(None),
#     db: Session = Depends(get_session),
# ):
#     if not agree:
#         raise HTTPException(status_code=400, detail="You must accept the Terms to create an account.")

#     existing = db.exec(select(User).where(User.email == email)).first()
#     if existing:
#         raise HTTPException(status_code=400, detail="Email already registered")

#     user = User(
#         email=email,
#         password=get_password_hash(password),
#         tier="free",
#         name=(name or email.split("@")[0].capitalize()),
#         created_at=datetime.utcnow(),
#         token_version=0,
#         tos_version=tosVersion or CURRENT_TOS_VERSION,
#         privacy_version=privacyVersion or CURRENT_PRIVACY_VERSION,
#         tos_accepted_at=datetime.utcnow(),
#         marketing_opt_in=bool(marketingOptIn),
#         consent_ip=request.client.host if request.client else None,
#         consent_ua=request.headers.get("user-agent"),
#     )
#     db.add(user); db.commit(); db.refresh(user)

#     token = create_access_token(user)
#     return {"email": user.email, "tier": user.tier, "name": user.name or "", "access_token": token}


# # ✅ LOGIN
# # @router.post("/login")
# # def login(
# #     email: str = Form(...),
# #     password: str = Form(...),
# #     db: Session = Depends(get_session)
# # ):
# #     user = db.exec(select(User).where(User.email == email)).first()
# #     # if not user or not pwd_context.verify(password, user.password):
# #     #     raise HTTPException(status_code=401, detail="Invalid credentials")

# #     # login:
# #     if not user or not verify_password(password, user.password):   # ← put this here
# #         raise HTTPException(status_code=401, detail="Invalid credentials")


# #     token = create_access_token(user)
# #     return {"email": user.email, "tier": user.tier, "name": user.name or "", "access_token": token}
# @router.post("/login")
# def login(
#     email: str = Form(...),
#     password: str = Form(...),
#     db: Session = Depends(get_session)
# ):
#     user = db.exec(select(User).where(User.email == email)).first()
#     if not user or not verify_password(password, user.password):
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     needs_reconsent = (
#         (user.tos_version or "") != CURRENT_TOS_VERSION
#         or (user.privacy_version or "") != CURRENT_PRIVACY_VERSION
#     )

#     token = create_access_token(user)
#     return {
#         "email": user.email,
#         "tier": user.tier,
#         "name": user.name or "",
#         "access_token": token,
#         "needs_reconsent": needs_reconsent,
#     }



# # ✅ CHANGE PASSWORD (invalidates all existing tokens)
# @router.post("/change-password")
# def change_password(
#     payload: ChangePasswordIn,
#     user_email: str = Depends(get_current_user),
#     db: Session = Depends(get_session),
# ):
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(status_code=401, detail="User not found")

#     user.password = get_password_hash(payload.newPassword)
    
#     user.token_version = (user.token_version or 0) + 1  # 🔒 revoke all current tokens
#     db.add(user)
#     db.commit()
#     return {"ok": True}

# # ✅ LOGOUT FROM ALL DEVICES (also invalidates all existing tokens)
# @router.post("/logout-all")
# def logout_all(
#     user_email: str = Depends(get_current_user),
#     db: Session = Depends(get_session),
# ):
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(status_code=401, detail="User not found")

#     user.token_version = (user.token_version or 0) + 1  # 🔒 revoke all current tokens
#     db.add(user)
#     db.commit()
#     return {"ok": True}


# @router.post("/accept-terms")
# def accept_terms(
#     request: Request,
#     user_email: str = Depends(get_current_user),
#     db: Session = Depends(get_session),
# ):
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(status_code=401, detail="User not found")

#     user.tos_version = CURRENT_TOS_VERSION
#     user.privacy_version = CURRENT_PRIVACY_VERSION
#     user.tos_accepted_at = datetime.utcnow()
#     user.consent_ip = request.client.host if request.client else None
#     user.consent_ua = request.headers.get("user-agent")
#     db.add(user); db.commit()
#     return {"ok": True}
