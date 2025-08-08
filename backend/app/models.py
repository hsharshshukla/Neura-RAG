from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Upload(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    filetype: str
    user_email: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    password: str
    tier: str = "free"
    name: Optional[str] = None  
    created_at: datetime = Field(default_factory=datetime.utcnow)  

class UploadedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    filename: str
    original_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class UsageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    event: str
    details: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
