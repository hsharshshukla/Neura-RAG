import os
from fastapi import Depends, HTTPException, Header
from jose import JWTError, jwt
from sqlmodel import Session, select
from app.db import get_session
from app.models import User
from .auth import get_current_user 

SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey")
ALGORITHM = "HS256"

def get_current_user(
    authorization: str = Header(None, alias="Authorization"),
    db: Session = Depends(get_session),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = authorization.replace("Bearer ", "", 1)
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        token_ver = int(payload.get("ver", 0))
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token: sub missing")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Enforce logout-all / password-rotate
    if (user.token_version or 0) != token_ver:
        raise HTTPException(status_code=401, detail="Token revoked; please log in again")

    # Your routes expect an email string
    return email
