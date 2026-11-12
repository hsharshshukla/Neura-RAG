# backend/app/models.py
from __future__ import annotations
from datetime import datetime, timedelta, date
from sqlalchemy import (
    Column,
    DateTime,
    text,
    JSON,
    UniqueConstraint,
    TIMESTAMP,
    func,
    CheckConstraint,
)
from sqlmodel import SQLModel, Field
from typing import Optional, List
from uuid import uuid4

try:
    from pydantic import field_validator  # Pydantic v2

    HAS_PYDANTIC_V2 = True
except ImportError:
    HAS_PYDANTIC_V2 = False


class Chat(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_email: str
    title: str = Field(default="New chat", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Upload(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    filetype: str
    user_email: str
    session_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    file_hash: Optional[str] = Field(default=None, index=True)
    text_hash: Optional[str] = Field(default=None, index=True)
    size_bytes: Optional[int] = Field(default=None)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    password: str | None = None
    tier: str = Field(default="free")  # 'free' | 'mini' | 'pro'
    role: str = Field(default="user", index=True)  # 'user' | 'admin'
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    token_version: int = Field(default=0)
    tos_version: Optional[str] = None
    tos_accepted_at: Optional[datetime] = None
    privacy_version: Optional[str] = None
    privacy_accepted_at: Optional[datetime] = None
    marketing_opt_in: bool = Field(default=False)
    consent_ip: Optional[str] = None
    consent_ua: Optional[str] = None
    email_verified_at: Optional[datetime] = None
    email_verification_token_hash: Optional[str] = Field(default=None, index=True)
    email_verification_expires_at: Optional[datetime] = None
    cancel_at_period_end: bool = Field(default=False, nullable=False)
    scheduled_plan: Optional[str] = Field(default=None)
    next_renewal_at: Optional[datetime] = Field(default=None)
    provider: str | None = Field(default=None, index=True, max_length=32)
    provider_id: str | None = Field(default=None, index=True, max_length=255)

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


class Workspace(SQLModel, table=True):
    id: str = Field(primary_key=True, max_length=36)
    name: str = Field(max_length=128)
    active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class WorkspaceMembership(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),)

    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True, max_length=36)
    user_id: int = Field(foreign_key="user.id", index=True)
    role: str = Field(default="reader", max_length=32)
    active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class UploadedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    filename: str
    original_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    workspace_id: str | None = Field(default=None, foreign_key="workspace.id", index=True)
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    timestamp: datetime = Field(
        sa_column=Column(
            DateTime(timezone=False),
            server_default=text("now()"),
            nullable=False,
            index=True,
        )
    )


class AnswerEvidenceAudit(SQLModel, table=True):
    """Append-only lineage for one TKP-backed runtime answer turn."""

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True, max_length=36)
    user_message_id: int = Field(foreign_key="chatmessage.id", unique=True)
    assistant_message_id: int = Field(foreign_key="chatmessage.id", unique=True)
    original_query: str
    standalone_query: str
    history_message_ids: list[int] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    tkp_correlation_id: str | None = Field(default=None, index=True, max_length=36)
    tkp_request: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    evidence_lineage: list[dict[str, object]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    backend_status: list[dict[str, object]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    citation_map: list[dict[str, object]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    answer_model: str = Field(max_length=128)
    prompt_policy_version: str = Field(max_length=64)
    validation_status: str = Field(max_length=32)
    insufficient_evidence: bool = Field(default=False, nullable=False)
    insufficient_reason: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class UsageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    event: str
    details: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


class PasswordResetToken(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: int = Field(index=True)
    token_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(index=True)
    used: bool = Field(default=False)

    @staticmethod
    def default_expiry(minutes: int = 30) -> datetime:
        return datetime.utcnow() + timedelta(minutes=minutes)


class DailyUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    day: date = Field(index=True)
    chats_count: int = Field(default=0)


class Coupon(SQLModel, table=True):
    __tablename__ = "coupon"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_coupon_amount_nonneg"),
        CheckConstraint(
            "(amount_type = 'percent' AND amount <= 100) OR "
            "(amount_type = 'fixed' AND amount <= 10000)",
            name="ck_coupon_amount_caps",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=128)
    amount: int
    amount_type: str = Field(max_length=16)
    duration: str = Field(max_length=16)
    duration_in_months: Optional[int] = None
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_limited_redemptions: bool = False
    max_redemptions: Optional[int] = None
    per_customer_limit: Optional[int] = None
    applies_to_variants: Optional[List[int]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    status: str = Field(default="active", max_length=16)
    currency: Optional[str] = Field(default=None, max_length=8)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )
    if HAS_PYDANTIC_V2:

        @field_validator("code", mode="before")
        def _upper_code(cls, v: object) -> object:
            return v.upper() if isinstance(v, str) else v


class CouponRedemption(SQLModel, table=True):
    __tablename__ = "coupon_redemption"
    __table_args__ = (
        UniqueConstraint("coupon_id", "user_id", "order_id", name="uq_coupon_user_order"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    coupon_id: int = Field(foreign_key="coupon.id", index=True)
    user_id: int = Field(index=True)
    order_id: Optional[str] = Field(default=None, max_length=128)
    amount_discounted: int
    currency: str = Field(max_length=8)
    redeemed_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


# # backend/app/models.py
# from __future__ import annotations
# from datetime import datetime, timedelta, date
# from sqlalchemy import Column, DateTime, text, JSON, UniqueConstraint, TIMESTAMP,func, CheckConstraint
# from sqlmodel import SQLModel, Field
# from typing import Optional, List
# from uuid import uuid4
# try:
#     from pydantic import field_validator  # Pydantic v2
#     HAS_PYDANTIC_V2 = True
# except ImportError:
#     HAS_PYDANTIC_V2 = False
# # --- existing models (mostly unchanged) ---

# class Chat(SQLModel, table=True):
#     id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
#     user_email: str
#     title: str = Field(default="New chat", index=True)
#     created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
#     updated_at: datetime = Field(default_factory=datetime.utcnow)


# class Upload(SQLModel, table=True):
#     id: Optional[int] = Field(default=None, primary_key=True)
#     filename: str
#     filetype: str
#     user_email: str
#     session_id: Optional[str] = Field(default=None, index=True)
#     created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
#     file_hash: Optional[str] = Field(default=None, index=True)
#     text_hash: Optional[str] = Field(default=None, index=True)
#     size_bytes: Optional[int] = Field(default=None)


# class User(SQLModel, table=True):
#     id: Optional[int] = Field(default=None, primary_key=True)
#     email: str
#     password: str
#     tier: str = Field(default="free")  # 'free' | 'mini' | 'pro'
#     role: str = Field(default="user", index=True)  # 'user' | 'admin'
#     name: Optional[str] = None
#     created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
#     token_version: int = Field(default=0)
#     tos_version: Optional[str] = None
#     tos_accepted_at: Optional[datetime] = None
#     privacy_version: Optional[str] = None
#     privacy_accepted_at: Optional[datetime] = None
#     marketing_opt_in: bool = Field(default=False)
#     consent_ip: Optional[str] = None
#     consent_ua: Optional[str] = None
#     email_verified_at: Optional[datetime] = None
#     email_verification_token_hash: Optional[str] = Field(default=None, index=True)
#     email_verification_expires_at: Optional[datetime] = None
#     cancel_at_period_end: bool = Field(default=False, nullable=False)
#     scheduled_plan: Optional[str] = Field(default=None)                # typically "free"
#     next_renewal_at: Optional[datetime] = Field(default=None)

#     @property
#     def is_email_verified(self) -> bool:
#         return self.email_verified_at is not None


# class UploadedFile(SQLModel, table=True):
#     id: Optional[int] = Field(default=None, primary_key=True)
#     user_id: int
#     filename: str
#     original_name: str
#     timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


# class ChatSession(SQLModel, table=True):
#     id: Optional[int] = Field(default=None, primary_key=True)
#     user_id: int
#     title: str
#     created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# class ChatMessage(SQLModel, table=True):
#     id: int | None = Field(default=None, primary_key=True)
#     session_id: int
#     user_id: int = Field(index=True)
#     role: str
#     content: str
#     created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

#     # DB default; no Field(index=/nullable=) when using sa_column
#     timestamp: datetime = Field(
#         sa_column=Column(
#             DateTime(timezone=False),
#             server_default=text("now()"),   # filled by Postgres
#             nullable=False,
#             index=True,                     # index is fine here
#         )
#     )


# class UsageLog(SQLModel, table=True):
#     id: Optional[int] = Field(default=None, primary_key=True)
#     user_id: int
#     event: str
#     details: Optional[str] = None
#     timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


# # --- Password reset token table (unchanged) ---

# class PasswordResetToken(SQLModel, table=True):
#     id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
#     user_id: int = Field(index=True)
#     token_hash: str
#     created_at: datetime = Field(default_factory=datetime.utcnow)
#     expires_at: datetime = Field(index=True)
#     used: bool = Field(default=False)

#     @staticmethod
#     def default_expiry(minutes: int = 30) -> datetime:
#         return datetime.utcnow() + timedelta(minutes=minutes)


# # --- Daily usage (unchanged) ---

# class DailyUsage(SQLModel, table=True):
#     id: Optional[int] = Field(default=None, primary_key=True)
#     user_id: int = Field(index=True, foreign_key="user.id")
#     day: date = Field(index=True)  # YYYY-MM-DD in server tz/UTC
#     chats_count: int = Field(default=0)


# class Coupon(SQLModel, table=True):
#     """
#     Gateway-agnostic coupon definition.
#     - Percent OR fixed amount discounts
#     - Duration: once | repeating (n months) | forever
#     - Optional start/end, global and per-customer limits
#     - Optional scoping to specific plan variants
#     - Store fixed amounts in MINOR units (paise/cents)
#     """
#     __tablename__ = "coupon"
#     __table_args__ = (
#         CheckConstraint("amount >= 0", name="ck_coupon_amount_nonneg"),
#         CheckConstraint(
#             "(amount_type = 'percent' AND amount <= 100) OR "
#             "(amount_type = 'fixed' AND amount <= 10000)",
#             name="ck_coupon_amount_caps",
#         ),
#     )
#     id: Optional[int] = Field(default=None, primary_key=True)
#     # Store code in UPPERCASE in app logic; we still index it here
#     code: str = Field(index=True, unique=True, max_length=64)
#     name: str = Field(max_length=128)

#     # Discount math
#     amount: int  # fixed: minor units; percent: 0-100
#     amount_type: str = Field(max_length=16)  # "percent" | "fixed"

#     # Duration semantics
#     duration: str = Field(max_length=16)  # "once" | "repeating" | "forever"
#     duration_in_months: Optional[int] = None  # required if duration=="repeating"

#     # Validity window (UTC)
#     starts_at: Optional[datetime] = None
#     expires_at: Optional[datetime] = None

#     # Usage limits
#     is_limited_redemptions: bool = False
#     max_redemptions: Optional[int] = None
#     per_customer_limit: Optional[int] = None  # e.g., 1 for first-purchase-only

#     # Optional scoping to your plan/price variants
#     applies_to_variants: Optional[List[int]] = Field(
#         default=None,
#         sa_column=Column(JSON, nullable=True),
#     )

#     # Operational flags
#     status: str = Field(default="active", max_length=16)  # "active" | "inactive" | "draft"
#     # Optional currency scoping for fixed discounts (e.g., "INR")
#     currency: Optional[str] = Field(default=None, max_length=8)

#     # Timestamps
#     created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
#     # updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
#     updated_at: datetime = Field(
#         sa_column=Column(
#             DateTime(timezone=False),
#             server_default=func.now(),
#             onupdate=func.now(),
#             nullable=False
#         )
#     )

#     if HAS_PYDANTIC_V2:
#         @field_validator("code", mode="before")
#         def _upper_code(cls, v):
#             return v.upper() if isinstance(v, str) else v

# class CouponRedemption(SQLModel, table=True):
#     """
#     Immutable audit of successful uses of a coupon.
#     Each row typically corresponds to a paid transaction (purchase or renewal).
#     """
#     __tablename__ = "coupon_redemption"
#     __table_args__ = (
#         UniqueConstraint("coupon_id", "user_id", "order_id", name="uq_coupon_user_order"),
#     )

#     id: Optional[int] = Field(default=None, primary_key=True)
#     coupon_id: int = Field(foreign_key="coupon.id", index=True)
#     user_id: int = Field(index=True)

#     # Provider reference (optional but great for idempotency)
#     order_id: Optional[str] = Field(default=None, max_length=128)

#     # How much was actually discounted on this transaction (minor units)
#     amount_discounted: int
#     currency: str = Field(max_length=8)

#     redeemed_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
