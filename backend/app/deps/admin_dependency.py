# backend/app/deps/admin_dependency.py
from fastapi import Depends, HTTPException, status
from sqlmodel import Session, select

from app.deps.auth import get_current_user
from app.db import get_session
from app.models import User

def get_current_admin(
    email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> User:
    user = db.exec(select(User).where(User.email == email.lower())).first()
    if not user or (getattr(user, "role", "user") != "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
