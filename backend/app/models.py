# backend/app/models.py
from typing import Optional
from datetime import datetime, timedelta, date
from uuid import uuid4

from sqlmodel import SQLModel, Field


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

# app/models.py (excerpt)
from sqlmodel import SQLModel, Field
from datetime import datetime

class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int
    user_id: int = Field(index=True)
    role: str
    content: str
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        index=True,
    )
    # new epoch-seconds column
    timestamp: int = Field(
        default_factory=lambda: int(datetime.utcnow().timestamp()),
        nullable=False,
        index=True,
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
