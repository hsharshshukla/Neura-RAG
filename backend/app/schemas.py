from pydantic import BaseModel
from datetime import datetime

class ChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime

    class Config:
        orm_mode = True

class ChatMessageOut(BaseModel):
    # id: int
    role: str
    content: str
    # timestamp: datetime

    class Config:
        orm_mode = True
