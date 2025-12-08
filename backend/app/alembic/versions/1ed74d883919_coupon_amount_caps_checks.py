"""coupon amount caps checks

Revision ID: 1ed74d883919
Revises: 20250907_add_coupons
Create Date: 2025-09-08 18:30:53.972378
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1ed74d883919"
down_revision: Union[str, None] = "20250907_add_coupons"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # amount must be non-negative
    op.create_check_constraint(
        constraint_name="ck_coupon_amount_nonneg",
        table_name="coupon",
        condition="amount >= 0",
    )

    # percent coupons: amount <= 100
    # fixed coupons:   amount <= 10000 (₹100 in minor units)
    op.create_check_constraint(
        constraint_name="ck_coupon_amount_caps",
        table_name="coupon",
        condition=(
            "(amount_type = 'percent' AND amount <= 100) OR "
            "(amount_type = 'fixed'   AND amount <= 10000)"
        ),
    )

    # Optional: require currency when amount_type is fixed
    # op.create_check_constraint(
    #     constraint_name="ck_coupon_fixed_currency_present",
    #     table_name="coupon",
    #     condition="(amount_type <> 'fixed') OR (currency IS NOT NULL)",
    # )


def downgrade() -> None:
    # If you enabled the optional constraint above, drop it first:
    # op.drop_constraint("ck_coupon_fixed_currency_present", "coupon", type_="check")

    op.drop_constraint("ck_coupon_amount_caps", "coupon", type_="check")
    op.drop_constraint("ck_coupon_amount_nonneg", "coupon", type_="check")
