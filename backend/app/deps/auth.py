# backend/app/deps/auth.py
import os
from fastapi import Depends, HTTPException, Header, status
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.db import get_session
from app.models import User

SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
ALGORITHM = os.getenv("JWT_ALG", "HS256")

def get_current_user(
    authorization: str = Header(None, alias="Authorization"),
    db: Session = Depends(get_session),
) -> str:
    """
    Validates Bearer JWT and returns the user's email (lowercased).
    Enforces token_version so logout-all / password-change invalidates old tokens.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
    db: Session = Depends(get_session),
) -> User:
    email = get_current_user(authorization, db)
    user = db.exec(select(User).where(User.email == email)).first()
    return user
