# backend/app/routes/checkout_intent.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func

from app.db import get_session
from app.deps.auth import get_current_user  # may return User or email (str)
from app.models import User, Coupon, CouponRedemption
from app.services.pricing import apply_coupon, PriceInput
from app.utils.signing import sign_payload

# Keep your existing prefix to avoid breaking the frontend.
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

# Must stay in sync with admin_coupons.py
HARD_MAX_BY_CURRENCY: Dict[str, int] = {
    "INR": 10000,  # ₹100.00
    "USD": 1200,   # $12.00
    # "EUR": 1200,
}

# --- helpers ---------------------------------------------------------------

def _resolve_user(user_or_email: Any, session: Session) -> Optional[User]:
    if isinstance(user_or_email, User):
        return user_or_email
    if isinstance(user_or_email, str):
        return session.exec(select(User).where(User.email == user_or_email)).first()
    return None


# --- schema ----------------------------------------------------------------

class CheckoutIntentReq(BaseModel):
    base_amount_minor: int                 # e.g., 49900 for ₹499
    currency: Annotated[str, Field(to_upper=True)] = "INR"
    coupon_code: Optional[Annotated[str, Field(strip_whitespace=True, to_upper=True)]] = None
    variant_id: Optional[int] = None       # optional: for scoping


# --- route -----------------------------------------------------------------

@router.post("/checkout-intent")
def checkout_intent(
    req: CheckoutIntentReq,
    user: Any = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    user_obj = _resolve_user(user, session)
    if not user_obj:
        raise HTTPException(401, detail="Unauthorized")

    # 1) Validate coupon (optional)
    coupon = None
    if req.coupon_code:
        coupon = session.exec(select(Coupon).where(Coupon.code == req.coupon_code)).first()
        if not coupon or coupon.status != "active":
            raise HTTPException(400, detail="Invalid coupon")

        now = datetime.utcnow()
        if coupon.starts_at and now < coupon.starts_at:
            raise HTTPException(400, detail="Coupon not yet active")
        if coupon.expires_at and now > coupon.expires_at:
            raise HTTPException(400, detail="Coupon expired")

        # Global limit
        if coupon.is_limited_redemptions and coupon.max_redemptions is not None:
            total_used = session.exec(
                select(func.count()).select_from(CouponRedemption).where(
                    CouponRedemption.coupon_id == coupon.id
                )
            ).one()
            if total_used >= coupon.max_redemptions:
                raise HTTPException(400, detail="Coupon limit reached")

        # Per-customer limit
        if coupon.per_customer_limit is not None:
            my_used = session.exec(
                select(func.count()).select_from(CouponRedemption).where(
                    CouponRedemption.coupon_id == coupon.id,
                    CouponRedemption.user_id == user_obj.id
                )
            ).one()
            if my_used >= coupon.per_customer_limit:
                raise HTTPException(400, detail="You’ve already used this coupon the maximum allowed times")

        # Variant scoping (optional)
        if coupon.applies_to_variants and req.variant_id is not None:
            if req.variant_id not in (coupon.applies_to_variants or []):
                raise HTTPException(400, detail="Coupon not applicable to this plan")

        # Currency scoping for fixed discounts (optional)
        if coupon.amount_type.lower() == "fixed":
            if not coupon.currency:
                raise HTTPException(400, detail="Fixed coupon is missing a currency")
            if coupon.currency.upper() != req.currency:
                raise HTTPException(400, detail="Coupon currency mismatch")

            # Apply currency-aware hard cap as additional safety
            hard_max = HARD_MAX_BY_CURRENCY.get(req.currency)
            if hard_max is None:
                raise HTTPException(400, detail=f"Unsupported currency at checkout: {req.currency}")
            if coupon.amount > hard_max:
                # Clamp to hard_max instead of failing (policy choice)
                coupon.amount = hard_max  # type: ignore[attr-defined]

    # 2) Compute payable for first cycle (defensive clamp to base)
    base = int(req.base_amount_minor)
    if base < 0:
        raise HTTPException(400, detail="Invalid base amount")

    payable, discount = apply_coupon(PriceInput(
        base_amount=base,
        currency=req.currency,
        coupon=coupon.dict() if coupon else None,
        cycle_index=0
    ))

    # Final safety: discount cannot exceed base; payable cannot be negative
    if discount > base:
        discount = base
        payable = 0
    if payable < 0:
        payable = 0

    # 3) Return a signed bundle for later webhook/callback validation
    bundle = sign_payload({
        "user_id": user_obj.id,
        "currency": req.currency,
        "base_amount": base,
        "payable_amount": payable,
        "coupon_code": coupon.code if coupon else None,
        "variant_id": req.variant_id,
    })

    return {
        "currency": req.currency,
        "base_amount_minor": base,
        "payable_amount_minor": payable,
        "discount_minor": discount,
        "signature_bundle": bundle,
        "coupon": (
            {
                "code": coupon.code,
                "amount": coupon.amount,
                "amount_type": coupon.amount_type,
                "duration": coupon.duration,
                "duration_in_months": coupon.duration_in_months
            } if coupon else None
        ),
    }
