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
    """
    Canonical email payload used across the app.

    Notes:
    - `from_` keeps Python keyword compatibility; exposed as "from" for providers via alias.
    - Use Field(default_factory=...) to avoid shared mutable defaults.
    """
    model_config = ConfigDict(from_attributes=True)

    subject: str
    from_: EmailAddress = Field(alias="from")
    to: List[EmailAddress] = Field(default_factory=list)

    # Body
    html: Optional[str] = None
    text: Optional[str] = None

    # Routing / headers
    cc: List[EmailAddress] = Field(default_factory=list)
    bcc: List[EmailAddress] = Field(default_factory=list)
    reply_to: Optional[EmailAddress] = None
    headers: Dict[str, str] = Field(default_factory=dict)

    # Attachments
    attachments: List[Attachment] = Field(default_factory=list)

    def has_body(self) -> bool:
        return bool((self.html and self.html.strip()) or (self.text and self.text.strip()))


class EmailSendResult(BaseModel):
    provider: str
    message_id: Optional[str] = None
    status: str  # "sent" | "queued" | "failed"
    raw: Dict[str, object] = Field(default_factory=dict)


# # app/email/models.py
# from __future__ import annotations
# from typing import List, Dict, Optional
# from pydantic import BaseModel, EmailStr, Field, ConfigDict

# class EmailAddress(BaseModel):
#     model_config = ConfigDict(from_attributes=True)
#     email: EmailStr
#     name: Optional[str] = None

# class Attachment(BaseModel):
#     model_config = ConfigDict(from_attributes=True)
#     filename: str
#     content_type: str
#     content: bytes  # raw bytes; providers will base64-encode

# class EmailMessage(BaseModel):
#     model_config = ConfigDict(from_attributes=True)
#     subject: str
#     from_: EmailAddress = Field(alias="from")
#     to: List[EmailAddress]
#     html: Optional[str] = None
#     text: Optional[str] = None
#     cc: List[EmailAddress] = []
#     bcc: List[EmailAddress] = []
#     reply_to: Optional[EmailAddress] = None
#     headers: Dict[str, str] = {}
#     attachments: List[Attachment] = []

# class EmailSendResult(BaseModel):
#     provider: str
#     message_id: Optional[str] = None
#     status: str  # "sent" | "queued"
#     raw: Optional[dict] = None
