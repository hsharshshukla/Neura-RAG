# app/deps/rbac.py
from fastapi import Depends, HTTPException, status
from app.deps.auth import get_current_user  # adjust import if your auth dep lives elsewhere

ALLOWED_ROLES = {
    "Owner",
    "Admin",
    "Finance",
    "Moderator",
    "Analyst",
    "Support",
    "ReadOnly",
}

def require_roles(*roles: str):
    """
    Usage:
      @router.get("/overview", dependencies=[Depends(require_roles("Owner","Admin","Analyst","ReadOnly"))])
    """
    def _inner(user = Depends(get_current_user)):
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
        role = getattr(user, "role", None)
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown role")
        if roles and role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user
    return _inner
