# backend/app/models.py
from __future__ import annotations

from typing import Optional
from datetime import datetime, timedelta, date
from uuid import uuid4

from sqlmodel import SQLModel, Field
# For DB-side defaults (so inserts via raw SQL/other clients also get timestamps)
from sqlalchemy import Column, TIMESTAMP, text
# app/models.py
from datetime import datetime, timedelta, date
from uuid import uuid4
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, text  # <-- add this import
from sqlalchemy import Column, DateTime, text
from sqlmodel import SQLModel, Field
from datetime import datetime
from sqlalchemy import Column, DateTime, text

# --- existing models (mostly unchanged) ---

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
    password: str
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

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


class UploadedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    filename: str
    original_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# --- ChatMessage: clean design (TIMESTAMP, not INT) ---

# ... other models ...

# app/models.py (excerpt)

class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int
    user_id: int = Field(index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # DB default; no Field(index=/nullable=) when using sa_column
    timestamp: datetime = Field(
        sa_column=Column(
            DateTime(timezone=False),
            server_default=text("now()"),   # filled by Postgres
            nullable=False,
            index=True,                     # index is fine here
        )
    )


class UsageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    event: str
    details: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


# --- Password reset token table (unchanged) ---

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


# --- Daily usage (unchanged) ---

class DailyUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    day: date = Field(index=True)  # YYYY-MM-DD in server tz/UTC
    chats_count: int = Field(default=0)

