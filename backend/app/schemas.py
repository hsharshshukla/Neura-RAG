# app/schemas.py
from pydantic import BaseModel, EmailStr
from datetime import datetime

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    accept_legal: bool  # must be true
    marketing_opt_in: bool = False
    tos_version: str
    privacy_version: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str | None = None
    tier: str

class ChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    class Config:
        orm_mode = True

class ChatMessageOut(BaseModel):
    role: str
    content: str
    class Config:
        orm_mode = True
