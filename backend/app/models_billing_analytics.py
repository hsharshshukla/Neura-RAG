# app/models_billing_analytics.py
from __future__ import annotations
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field

class LLMUsageEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    chat_session_id: Optional[int] = None
    tier: str
    model: str
    provider: str  # 'openai'
    request_tokens: int
    response_tokens: int
    total_tokens: int
    latency_ms: int
    cost_micro_usd: int
    currency: str = "USD"
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    # Diagnostics
    retrieved_chunks: int = 0
    retrieved_tokens: int = 0
    embeddings_tokens: int = 0
    http_status: int = 200
    error_code: Optional[str] = None
    cache_hit: bool = False
