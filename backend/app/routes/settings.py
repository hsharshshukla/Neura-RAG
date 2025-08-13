# app/routes/settings.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from datetime import datetime
from typing import Optional
from app.utils.security import get_password_hash

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user

# app/core/settings.py
TOS_VERSION = "2025-08-12"
PRIVACY_VERSION = "2025-08-12"

# password hashing (use your existing helper if you have one)
try:
    from app.utils.security import get_password_hash  # preferred
except Exception:
    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    def get_password_hash(p: str) -> str:
        return _pwd.hash(p)

router = APIRouter(prefix="/api/v1", tags=["settings"])

class MeOut(BaseModel):
    email: str
    name: Optional[str] = None
    tier: Optional[str] = None
    created_at: Optional[datetime] = None

class MePatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)

class ChangePasswordIn(BaseModel):
    newPassword: str = Field(min_length=6, max_length=256)

@router.get("/user/me", response_model=MeOut)
def get_me(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return MeOut(
        email=user.email,
        name=user.name,
        tier=user.tier,
        created_at=user.created_at,
    )

@router.patch("/user/me")
def update_me(
    payload: MePatch,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    new_name = " ".join(payload.name.split())[:80]
    user.name = new_name
    db.add(user)
    db.commit()
    return {"ok": True, "name": new_name}

@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordIn,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.password = get_password_hash(payload.newPassword)
    # bump token_version so old JWTs become invalid
    if hasattr(user, "token_version"):
        user.token_version = (user.token_version or 0) + 1

    db.add(user)
    db.commit()
    return {"ok": True}

@router.post("/auth/logout-all")
def logout_all_devices(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not hasattr(user, "token_version"):
        raise HTTPException(status_code=500, detail="Server missing token_version column on users")

    user.token_version = (user.token_version or 0) + 1
    db.add(user)
    db.commit()
    return {"ok": True}


@router.get("/user/profile")
def get_profile(user_email: str = Depends(get_current_user), db: Session = Depends(get_session)):
    # simple alias to /user/me
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # keep it lenient – if name is None, return empty string to not break UI
    return {
        "email": user.email,
        "name": user.name or "",
        "tier": user.tier,
        "created_at": user.created_at,
    }
