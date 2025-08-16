# app/deps/auth.py
import os
from typing import Optional
from fastapi import Depends, HTTPException, Header, Cookie, status
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.db import get_session
from app.models import User

SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
ALGORITHM = os.getenv("JWT_ALG", "HS256")
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "access_token")


def _decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def get_current_user(
    authorization: str = Header(None, alias="Authorization"),
    access_cookie: Optional[str] = Cookie(None, alias=ACCESS_COOKIE_NAME),
    db: Session = Depends(get_session),
) -> str:
    """
    Validates JWT from either Bearer Authorization header OR HttpOnly cookie.
    Returns the user's email (lowercased). Enforces token_version.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif access_cookie:
        token = access_cookie

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")

    try:
        payload = _decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    email = (payload.get("sub") or "").lower()
    token_ver = int(payload.get("ver", 0))
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: sub missing")

    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if int(user.token_version or 0) != token_ver:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked; please log in again")

    return email


def get_current_user_obj(
    authorization: str = Header(None, alias="Authorization"),
    access_cookie: Optional[str] = Cookie(None, alias=ACCESS_COOKIE_NAME),
    db: Session = Depends(get_session),
) -> User:
    email = get_current_user(authorization, access_cookie, db)
    user = db.exec(select(User).where(User.email == email)).first()
    return user
