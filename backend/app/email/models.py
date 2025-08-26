# app/email/models.py
from __future__ import annotations
from typing import List, Dict, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class EmailAddress(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: EmailStr
    name: Optional[str] = None

class Attachment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    filename: str
    content_type: str
    content: bytes  # raw bytes; providers will base64-encode

class EmailMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subject: str
    from_: EmailAddress = Field(alias="from")
    to: List[EmailAddress]
    html: Optional[str] = None
    text: Optional[str] = None
    cc: List[EmailAddress] = []
    bcc: List[EmailAddress] = []
    reply_to: Optional[EmailAddress] = None
    headers: Dict[str, str] = {}
    attachments: List[Attachment] = []

class EmailSendResult(BaseModel):
    provider: str
    message_id: Optional[str] = None
    status: str  # "sent" | "queued"
    raw: Optional[dict] = None
