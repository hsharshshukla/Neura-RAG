# app/utils/llm_logger.py
from __future__ import annotations
from typing import Optional
from sqlmodel import Session
from app.models_billing_analytics import LLMUsageEvent
from app.utils.costs import estimate_cost_micro_usd

def log_llm_event(
    db: Session,
    *,
    user_id: int,
    tier: str,
    model: str,
    provider: str,
    request_tokens: int,
    response_tokens: int,
    latency_ms: int,
    chat_session_id: Optional[int] = None,
    retrieved_chunks: int = 0,
    retrieved_tokens: int = 0,
    embeddings_tokens: int = 0,
    http_status: int = 200,
    error_code: Optional[str] = None,
    cache_hit: bool = False,
) -> None:
    ev = LLMUsageEvent(
        user_id=user_id,
        chat_session_id=chat_session_id,
        tier=tier,
        model=model,
        provider=provider,
        request_tokens=request_tokens,
        response_tokens=response_tokens,
        total_tokens=request_tokens + response_tokens,
        latency_ms=latency_ms,
        cost_micro_usd=estimate_cost_micro_usd(model, request_tokens, response_tokens),
        retrieved_chunks=retrieved_chunks,
        retrieved_tokens=retrieved_tokens,
        embeddings_tokens=embeddings_tokens,
        http_status=http_status,
        error_code=error_code,
        cache_hit=cache_hit,
    )
    db.add(ev); db.commit()
