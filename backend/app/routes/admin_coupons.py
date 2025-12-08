# backend/app/routes/admin_coupons.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select, func

from app.db import get_session
from app.deps.auth import get_current_user  # may return User OR email (str)
from app.models import User, Coupon, CouponRedemption

# Keep this prefix (frontend calls "/admin/coupons" via secureAxios base /api/v1)
router = APIRouter(prefix="/api/v1/admin/coupons", tags=["admin:coupons"])

# Currency-aware hard caps for fixed discounts (minor units).
# Adjust as you add currencies / change price points.
HARD_MAX_BY_CURRENCY: Dict[str, int] = {
    "INR": 10000,   # ₹100.00 (paise)
    "USD": 1200,    # $12.00 (cents)
    # "EUR": 1200,  # example: €12.00
}

# --- helpers ---------------------------------------------------------------

def _resolve_user(user_or_email: Any, session: Session) -> Optional[User]:
    """Return a User whether dependency gave us a User object or an email string."""
    if isinstance(user_or_email, User):
        return user_or_email
    if isinstance(user_or_email, str):
        return session.exec(select(User).where(User.email == user_or_email)).first()
    return None


def _ensure_admin(user_or_email: Any, session: Session) -> User:
    u = _resolve_user(user_or_email, session)
    if not u or u.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return u


# --- schema ----------------------------------------------------------------

class CouponCreate(BaseModel):
    code: Annotated[str, Field(strip_whitespace=True, to_upper=True, min_length=3, max_length=64)]
    name: Annotated[str, Field(strip_whitespace=True, min_length=3, max_length=128)]

    amount: int
    amount_type: Annotated[str, Field(to_lower=True)]  # "percent" | "fixed"

    duration: Annotated[str, Field(to_lower=True)]     # "once" | "repeating" | "forever"
    duration_in_months: Optional[int] = None

    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    is_limited_redemptions: bool = False
    max_redemptions: Optional[int] = None
    per_customer_limit: Optional[int] = None

    applies_to_variants: Optional[List[int]] = None

    status: Annotated[str, Field(to_lower=True)] = "active"  # "active" | "inactive" | "draft"
    currency: Optional[Annotated[str, Field(to_upper=True, max_length=8)]] = None  # required when fixed

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amount must be >= 0")
        return v

    @field_validator("amount_type")
    @classmethod
    def _check_amount_type(cls, v: str) -> str:
        if v not in ("percent", "fixed"):
            raise ValueError("amount_type must be 'percent' or 'fixed'")
        return v

    @field_validator("duration")
    @classmethod
    def _check_duration(cls, v: str) -> str:
        if v not in ("once", "repeating", "forever"):
            raise ValueError("duration must be 'once', 'repeating' or 'forever'")
        return v


# --- routes ----------------------------------------------------------------

@router.post("", status_code=201)
def create_coupon(
    body: CouponCreate,
    user: Any = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _ensure_admin(user, session)

    # semantics (frontend also enforces; this is defense-in-depth)
    if body.duration == "repeating" and (body.duration_in_months is None or body.duration_in_months <= 0):
        raise HTTPException(400, detail="duration_in_months must be > 0 for repeating coupons")

    if body.amount_type == "percent":
        if body.amount > 100:
            raise HTTPException(400, detail="percent coupons cannot exceed 100")
    else:
        # fixed = currency-aware validation
        if not body.currency:
            raise HTTPException(400, detail="currency is required when amount_type is 'fixed'")
        cur = body.currency.upper()
        hard_max = HARD_MAX_BY_CURRENCY.get(cur)
        if hard_max is None:
            raise HTTPException(400, detail=f"Unsupported currency for fixed coupon: {cur}")
        if body.amount > hard_max:
            raise HTTPException(400, detail=f"fixed coupons cannot exceed {cur} {hard_max} minor units")

    # uniqueness
    existing = session.exec(select(Coupon).where(Coupon.code == body.code.upper())).first()
    if existing:
        raise HTTPException(409, detail="Coupon code already exists")

    # create
    c = Coupon(
        code=body.code.upper(),
        name=body.name,
        amount=body.amount,
        amount_type=body.amount_type,
        duration=body.duration,
        duration_in_months=body.duration_in_months,
        starts_at=body.starts_at,
        expires_at=body.expires_at,
        is_limited_redemptions=body.is_limited_redemptions,
        max_redemptions=body.max_redemptions,
        per_customer_limit=body.per_customer_limit,
        applies_to_variants=body.applies_to_variants,
        status=body.status,
        currency=(body.currency.upper() if body.currency else None),
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c  # SQLModel serializes nicely


@router.get("")
def list_coupons(
    user: Any = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _ensure_admin(user, session)
    rows = session.exec(select(Coupon).order_by(Coupon.created_at.desc())).all()
    return rows


@router.delete("/{coupon_id}")
def delete_coupon(
    coupon_id: Annotated[int, Path(..., ge=1)],
    user: Any = Depends(get_current_user),
    session: Session = Depends(get_session),
    # allow ?force=true in future to bypass safety if needed
    force: bool = Query(False),
):
    _ensure_admin(user, session)

    c = session.get(Coupon, coupon_id)
    if not c:
        raise HTTPException(404, detail="Coupon not found")

    # Block delete if any redemptions exist (keep audit trails)
    redemptions = session.exec(
        select(func.count()).select_from(CouponRedemption).where(CouponRedemption.coupon_id == coupon_id)
    ).one()
    if redemptions and redemptions > 0 and not force:
        raise HTTPException(400, detail="Cannot delete a coupon that has redemptions. Set status 'inactive' instead.")

    session.delete(c)
    session.commit()
    return {"ok": True, "deleted_id": coupon_id}
