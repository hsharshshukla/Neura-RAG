# app/deps/rbac.py
from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.deps.auth import get_current_user_obj
from app.models import User

ALLOWED_ROLES = {
    "owner",
    "admin",
    "finance",
    "moderator",
    "analyst",
    "support",
    "readonly",
    "user",
}


def require_roles(*roles: str) -> Callable[[User], User]:
    """
    Use this dependency on routes that require one of the supplied roles.
    """
    normalized_required = {role.lower() for role in roles}

    def _inner(user: User = Depends(get_current_user_obj)) -> User:
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
        role = (getattr(user, "role", "") or "").lower()
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown role")
        if normalized_required and role not in normalized_required:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _inner
