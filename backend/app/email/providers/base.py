# app/email/providers/base.py
from __future__ import annotations
from typing import Protocol
from app.email.models import EmailMessage, EmailSendResult

class EmailProvider(Protocol):
    name: str
    async def send(self, msg: EmailMessage) -> EmailSendResult: ...
