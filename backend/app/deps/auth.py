# app/deps/auth.py

from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.config.security import get_security_settings
from app.db import get_session
from app.models import User


def _decode_token(token: str) -> dict[str, Any]:
    settings = get_security_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_alg],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require_exp": True, "require_iat": True, "require_sub": True},
    )
    return dict(payload)


def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    access_cookie: str | None = Cookie(None, alias="access_token"),
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
    except (JWTError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
        ) from None

    email = (payload.get("sub") or "").lower()
    token_ver = int(payload.get("ver", 0))
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
        )

    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
        )

    if int(user.token_version or 0) != token_ver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
        )

    return email


def get_current_user_obj(
    authorization: str | None = Header(None, alias="Authorization"),
    access_cookie: str | None = Cookie(None, alias="access_token"),
    db: Session = Depends(get_session),
) -> User:
    email = get_current_user(authorization, access_cookie, db)
    user = db.exec(select(User).where(User.email == email)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return user
