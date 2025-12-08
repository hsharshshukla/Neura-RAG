# app/routes/admin_users_bulk.py
from __future__ import annotations
from typing import List, Literal, Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.deps.auth import get_current_user
from app.models import User  # id (INTEGER), email, role (TEXT/ENUM), status ("active"/"deactivated")
# from app.services.auth import issue_password_reset
# from app.services.mailer import send_reset_email

router = APIRouter(prefix="/api/v1/admin/users/bulk", tags=["admin:users:bulk"])

# ----- Schemas ---------------------------------------------------------------

Operation = Literal["reset_password", "deactivate", "reactivate", "change_role"]

class BulkRequest(BaseModel):
    user_ids: List[int] = Field(..., min_items=1)  # integers to match DB
    op: Operation
    new_role: Optional[str] = None
    reason: Optional[str] = None
    dry_run: bool = False
    idempotency_key: Optional[str] = None

class BulkResultItem(BaseModel):
    user_id: str
    ok: bool
    message: Optional[str] = None
    changed: Dict[str, Any] = {}

class BulkResponse(BaseModel):
    op: Operation
    count_requested: int
    count_succeeded: int
    results: List[BulkResultItem]
    at: str

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ----- Role normalization / storage mapping ----------------------------------

# Roles you expose in the UI
ALLOWED_ROLE_SET = {"Owner", "Admin", "Support", "Finance", "Analyst", "ReadOnly", "User"}

# Accept case-insensitive inputs + a few variants
CANONICAL_ROLES = {
    "owner": "Owner",
    "admin": "Admin",
    "support": "Support",
    "finance": "Finance",
    "analyst": "Analyst",
    "readonly": "ReadOnly",
    "read_only": "ReadOnly",
    "read-only": "ReadOnly",
    "user": "User",
}

def normalize_role(val: Optional[str]) -> str:
    if not val:
        return ""
    key = val.strip().lower()
    return CANONICAL_ROLES.get(key, val)

# ------- IMPORTANT: choose how to store in DB --------------------------------
# If your DB column was historically lowercase enum ('user'/'admin'), set this False.
# If your DB column is a free TEXT and you want the pretty TitleCase values in DB, set True.
STORE_TITLE_CASE_IN_DB = False

LOWER_STORAGE_MAP = {
    "Owner": "owner",
    "Admin": "admin",
    "Support": "support",
    "Finance": "finance",
    "Analyst": "analyst",
    "ReadOnly": "readonly",
    "User": "user",
}

def to_storage_role(canonical: str) -> str:
    return canonical if STORE_TITLE_CASE_IN_DB else LOWER_STORAGE_MAP.get(canonical, canonical.lower())

# ----- Auth guard (relaxed per your request) ---------------------------------
ALLOW_SELF_CHANGE = True  # set False if you want to prevent changing your own role

def _ensure_can_manage(actor: User, target: User):
    # Require authenticated admin/owner to perform bulk changes.
    # If you want to allow any authenticated user (dev-only), relax this further.
    if (actor.role or "").strip().lower() not in {"owner", "admin"}:
        raise HTTPException(403, "Admin required")

    if not ALLOW_SELF_CHANGE and str(actor.id) == str(target.id):
        raise HTTPException(400, "Refusing to act on your own account")

    # NOTE: No Owner restrictions or last-Owner checks (per your requirement).

# ----- Endpoint ---------------------------------------------------------------

@router.post("", response_model=BulkResponse)
def bulk_admin_users(
    payload: BulkRequest = Body(...),
    session: Session = Depends(get_session),
    actor: User = Depends(get_current_user),
):
    ids = list(dict.fromkeys([int(x) for x in payload.user_ids]))
    if not ids or any(i <= 0 for i in ids):
        raise HTTPException(400, "user_ids must be positive integers")

    results: List[BulkResultItem] = []
    ok_count = 0

    targets = session.exec(select(User).where(User.id.in_(ids))).all()
    by_id = {int(u.id): u for u in targets}

    # Validate / normalize op-specific inputs
    if payload.op == "change_role":
        newr = normalize_role(payload.new_role)
        if not newr or newr not in ALLOWED_ROLE_SET:
            raise HTTPException(400, f"new_role must be one of {sorted(ALLOWED_ROLE_SET)}")
        payload.new_role = newr

    for uid in ids:
        u = by_id.get(uid)
        if not u:
            results.append(BulkResultItem(user_id=str(uid), ok=False, message="User not found"))
            continue

        try:
            _ensure_can_manage(actor, u)

            if payload.dry_run:
                results.append(BulkResultItem(user_id=str(uid), ok=True, message="Dry-run"))
                ok_count += 1
                continue

            changed: Dict[str, Any] = {}

            if payload.op == "reset_password":
                # token = issue_password_reset(session, u)
                # send_reset_email(u.email, token)
                changed["reset_dispatched"] = True
                msg = "Password reset email queued."

            elif payload.op == "deactivate":
                if getattr(u, "status", "active") != "deactivated":
                    u.status = "deactivated"
                    try:
                        u.token_version = (u.token_version or 0) + 1
                        changed["token_version"] = u.token_version
                    except Exception:
                        pass
                    changed["status"] = "deactivated"
                msg = "User deactivated."

            elif payload.op == "reactivate":
                if getattr(u, "status", "active") != "active":
                    u.status = "active"
                    changed["status"] = "active"
                msg = "User reactivated."

            elif payload.op == "change_role":
                # Canonical (UI) -> storage format mapping
                target_canonical = payload.new_role  # already canonical
                target_storage = to_storage_role(target_canonical)
                if (u.role or "") != target_storage:
                    u.role = target_storage
                    changed["role"] = target_storage
                msg = f"Role set to {target_canonical}."

            else:
                raise HTTPException(400, f"Unsupported op: {payload.op}")

            session.add(u)
            results.append(BulkResultItem(user_id=str(uid), ok=True, message=msg, changed=changed))
            ok_count += 1

        except HTTPException as he:
            results.append(BulkResultItem(user_id=str(uid), ok=False, message=he.detail))
        except IntegrityError as ie:
            # e.g., enum constraint mismatch; this tells you exactly what's wrong
            results.append(BulkResultItem(user_id=str(uid), ok=False, message=f"DB constraint: {ie.orig}"))
        except Exception as e:
            results.append(BulkResultItem(user_id=str(uid), ok=False, message=str(e)))

    session.commit()
    return BulkResponse(
        op=payload.op,
        count_requested=len(ids),
        count_succeeded=ok_count,
        results=results,
        at=_now_iso(),
    )
