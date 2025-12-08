# backend/app/analytics/deps.py
from __future__ import annotations

import uuid
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Dict, Optional, Generator

from fastapi import Request
from sqlmodel import Session

from app.analytics.logger import log_chat_event  # Core insert into chat_event


def _as_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _as_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


@contextmanager
def chat_event_recorder(
    *,
    request: Request,
    db: Session,
    user_id: Any,                  # TEXT in DB (email / id / uuid) – we pass through
    plan: Optional[str],
    chat_session_id: Any,          # UUID in DB; logger coerces safely
    message_index: int,
    model: str,
    provider: str = "openai",
    intent: Optional[str] = None,
    topic: Optional[str] = None,
    pipeline_version: Optional[str] = None,
) -> Generator[None, None, None]:
    """
    Wrap a chat turn; measures latency, reads metrics from request.state, inserts into chat_event.

    You may set any of these on request.state inside the with-block:
      input_tokens, output_tokens, in_cost, out_cost, total_cost, response_code,
      retrieved, retrieval_latency_ms, rag_k, rag_hit, rag_hit_confidence,
      rag_source_kinds, rag_doc_ids_hash, refused, policy_trigger,
      thumb, csat, feedback_comment, error_kind, stack_key
    """
    started = perf_counter()
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    error_kind: Optional[str] = None

    try:
        yield
    except Exception as e:
        error_kind = type(e).__name__
        raise
    finally:
        latency_ms = int((perf_counter() - started) * 1000)

        st = getattr(request, "state", None)

        # tokens & cost
        input_tokens = _as_int(getattr(st, "input_tokens", 0))
        output_tokens = _as_int(getattr(st, "output_tokens", 0))
        in_cost = _as_float(getattr(st, "in_cost", 0))
        out_cost = _as_float(getattr(st, "out_cost", 0))
        total_cost = _as_float(getattr(st, "total_cost", in_cost + out_cost))

        # response / status
        response_code = _as_int(getattr(st, "response_code", 200))

        # retrieval
        retrieved = bool(getattr(st, "retrieved", False))
        retrieval_latency_ms = _as_int(getattr(st, "retrieval_latency_ms", 0))
        rag_k = getattr(st, "rag_k", None)
        rag_hit = getattr(st, "rag_hit", None)
        rag_hit_confidence = getattr(st, "rag_hit_confidence", None)
        rag_source_kinds = getattr(st, "rag_source_kinds", None)
        rag_doc_ids_hash = getattr(st, "rag_doc_ids_hash", None)

        # policy
        refused = bool(getattr(st, "refused", False))
        policy_trigger = getattr(st, "policy_trigger", None)

        # quality
        thumb = getattr(st, "thumb", None)
        csat = getattr(st, "csat", None)
        feedback_comment = getattr(st, "feedback_comment", None)

        # errors
        err_kind = error_kind or getattr(st, "error_kind", None)
        stack_key = getattr(st, "stack_key", None)

        payload: Dict[str, Any] = {
            "request_id": req_id,
            "user_id": user_id,                    # TEXT in DB
            "plan": plan,
            "chat_session_id": chat_session_id,    # coerced to UUID by logger
            "message_index": message_index,

            "model": model,
            "provider": provider,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "response_code": response_code,

            "in_cost": in_cost,
            "out_cost": out_cost,
            "total_cost": total_cost,

            "retrieved": retrieved,
            "retrieval_latency_ms": retrieval_latency_ms,
            "rag_k": rag_k,
            "rag_hit": rag_hit,
            "rag_hit_confidence": rag_hit_confidence,
            "rag_source_kinds": rag_source_kinds,
            "rag_doc_ids_hash": rag_doc_ids_hash,

            "refused": refused,
            "policy_trigger": policy_trigger,

            "thumb": thumb,
            "csat": csat,
            "feedback_comment": feedback_comment,

            "intent": intent,
            "topic": topic,
            "pipeline_version": pipeline_version,

            "error_kind": err_kind,
            "stack_key": stack_key,
        }

        # Write the row and FLUSH so it appears in SELECTs even before commit.
        # (Commit still happens in the route after messages are saved.)
        log_chat_event(db, payload)
        try:
            db.flush()
        except Exception:
            # Non-fatal: the logger already reported any insert issue; keep request flow alive
            pass
