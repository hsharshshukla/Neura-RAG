# backend/app/services/pricing.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class PriceInput:
    base_amount: int          # e.g., 49900 paise = ₹499.00
    currency: str             # "INR"
    coupon: Optional[Dict[str, Any]]  # dict(Coupon) or None
    cycle_index: int = 0      # 0 = first charge, 1 = next month, ...

def apply_coupon(pi: PriceInput) -> tuple[int, int]:
    """
    Returns (payable_amount, discount_applied).
    Applies coupon only if active for this cycle.
    """
    if not pi.coupon:
        return pi.base_amount, 0

    c = pi.coupon

    # duration logic
    active = False
    dur = (c.get("duration") or "").lower()
    if dur == "once":
        active = pi.cycle_index == 0
    elif dur == "forever":
        active = True
    elif dur == "repeating":
        n = int(c.get("duration_in_months") or 0)
        active = pi.cycle_index < n

    if not active:
        return pi.base_amount, 0

    # amount logic
    amt_type = (c.get("amount_type") or "").lower()
    amt = int(c.get("amount") or 0)
    if amt_type == "percent":
        discount = (pi.base_amount * amt) // 100
    else:  # fixed
        discount = min(amt, pi.base_amount)

    payable = max(0, pi.base_amount - discount)
    return payable, discount
