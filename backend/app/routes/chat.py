from __future__ import annotations

import asyncio
import json
import os, re, time, uuid, logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Optional, List, Any, Dict
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, col, select, func
from sqlalchemy.exc import IntegrityError
from openai import OpenAI

from app.db import get_session
from app.models import AnswerEvidenceAudit, ChatSession, ChatMessage, User
from app.schemas import ChatSessionOut, ChatMessageOut
from app.deps.auth import get_current_user
from app.deps.chat_session import require_owned_chat_session
from app.deps.workspace import require_tkp_workspace_access
from app.integrations.tkp.client import TKPClient, TKPClientError
from app.integrations.tkp.config import get_tkp_settings
from app.integrations.tkp.schemas import (
    BrowserRetrievalRequest,
    TKPRetrievalRequest,
    TKPRetrievalResponse,
)
from app.services.conversation_context import (
    AMBIGUOUS_CONTEXT_MESSAGE,
    CONTEXT_PROMPT_POLICY_VERSION,
    BoundedConversationContext,
    ContextMessage,
    ConversationContextSettings,
    build_bounded_context,
    resolve_conversation_query,
)
from app.services.evidence_audit import build_answer_evidence_audit
from app.services.grounded_answer import (
    GROUNDING_PROMPT_POLICY_VERSION,
    GroundedAnswer,
    GroundingError,
    generate_grounded_answer,
)
from app.utils.logger import log_event
from app.vector_store import query_user_docs
from app.rate_limit import limiter

from app.config.plan_policy import (
    plan_limit,
    plan_model,
    plan_for,
    caps_for,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = logging.getLogger("neura.chat")


# =========================
# Models
# =========================
class ChatIn(BaseModel):
    message: str
    session_id: Optional[int] = None


class RenameIn(BaseModel):
    title: str


class StreamChatIn(BaseModel):
    message: str
    session_id: int | None = None
    request_id: uuid.UUID


# =========================
# Helpers
# =========================
def env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def sanitize_user_input(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def wrap_user_content(text: str) -> str:
    return f"USER_CONTENT_START\n{text}\nUSER_CONTENT_END"


def _tier_name(user: Any) -> str:
    return plan_for(user).name


def _title_from_text(text: str) -> str:
    s = " ".join(text.split())
    return (s[:60] + "…") if len(s) > 60 else s or "New Chat"


def _today_user_chat_count(db: Session, user_id: int) -> int:
    start = datetime.combine(date.today(), datetime.min.time())
    end = datetime.combine(date.today(), datetime.max.time())
    return db.exec(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
            ChatMessage.created_at.between(start, end),
        )
    ).one()


def _session_uuid(session_id: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"chat-session:{session_id}")


def _messages_in_session(db: Session, session_id: int) -> int:
    return db.exec(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    ).one()


def _authorized_tkp_workspace_id(*, user: User, db: Session) -> str | None:
    if env("ORGANIZATIONAL_RAG_MODE", "legacy").lower() != "tkp":
        return None
    try:
        settings = get_tkp_settings()
    except ValidationError as exc:
        raise HTTPException(503, "Knowledge retrieval is not configured") from exc
    access = require_tkp_workspace_access(user=user, db=db, settings=settings)
    return str(access.workspace_id)


def _load_bounded_history(
    db: Session, *, session_id: int, user_id: int
) -> BoundedConversationContext:
    settings = ConversationContextSettings.from_environment()
    rows = db.exec(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.user_id == user_id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(settings.max_messages * 4)
    ).all()
    messages = [
        ContextMessage(message_id=row.id, role=row.role, content=row.content)
        for row in reversed(rows)
        if row.id is not None and row.role in {"user", "assistant"} and row.content.strip()
    ]
    return build_bounded_context(messages, settings)


def _persist_tkp_turn(
    db: Session,
    *,
    chat: ChatSession | None,
    user: User,
    workspace_id: str,
    original_query: str,
    standalone_query: str,
    history: BoundedConversationContext,
    retrieval_request: TKPRetrievalRequest | None,
    retrieval: TKPRetrievalResponse | None,
    grounded: GroundedAnswer,
    model: str,
    validation_status: str,
    client_request_id: str | None = None,
) -> tuple[ChatSession, bool]:
    created_new = chat is None
    try:
        if chat is None:
            chat = ChatSession(
                user_id=user.id,
                workspace_id=workspace_id,
                title=_title_from_text(original_query),
            )
            db.add(chat)
            db.flush()
        if chat.id is None or user.id is None:
            raise RuntimeError("Chat persistence identifiers were not assigned")

        now = datetime.utcnow()
        user_message = ChatMessage(
            session_id=chat.id,
            user_id=user.id,
            role="user",
            content=original_query,
            created_at=now,
            timestamp=now,
        )
        assistant_message = ChatMessage(
            session_id=chat.id,
            user_id=user.id,
            role="assistant",
            content=grounded.answer,
            created_at=now,
            timestamp=now,
        )
        db.add(user_message)
        db.add(assistant_message)
        db.flush()
        if user_message.id is None or assistant_message.id is None:
            raise RuntimeError("Message persistence identifiers were not assigned")

        prompt_version = (
            CONTEXT_PROMPT_POLICY_VERSION
            if validation_status == "AMBIGUOUS_CONTEXT"
            else GROUNDING_PROMPT_POLICY_VERSION
        )
        db.add(
            build_answer_evidence_audit(
                session_id=chat.id,
                user_id=user.id,
                workspace_id=workspace_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                original_query=original_query,
                standalone_query=standalone_query,
                history_message_ids=history.message_ids,
                retrieval_request=retrieval_request,
                retrieval=retrieval,
                answer=grounded,
                answer_model=model,
                prompt_policy_version=prompt_version,
                validation_status=validation_status,
                client_request_id=client_request_id,
            )
        )
        db.commit()
        db.refresh(chat)
        return chat, created_new
    except Exception:
        db.rollback()
        raise


def _stream_chunk_size() -> int:
    return min(max(env_int("TKP_CHAT_STREAM_CHUNK_CHARACTERS", 240), 64), 1024)


def _stream_timeout_seconds() -> float:
    try:
        value = float(env("TKP_CHAT_STREAM_TIMEOUT_SECONDS", "90"))
    except ValueError:
        value = 90
    return min(max(value, 5), 120)


def _sse_event(event: str, data: dict[str, object], event_id: int) -> str:
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


def _bounded_answer_chunks(answer: str) -> tuple[str, ...]:
    size = _stream_chunk_size()
    return tuple(answer[index : index + size] for index in range(0, len(answer), size))


def _replay_stream_payload(
    db: Session,
    *,
    user: User,
    workspace_id: str,
    client_request_id: str,
    original_query: str,
    requested_session_id: int | None,
) -> dict[str, object] | None:
    audit = db.exec(
        select(AnswerEvidenceAudit).where(
            AnswerEvidenceAudit.user_id == user.id,
            AnswerEvidenceAudit.workspace_id == workspace_id,
            AnswerEvidenceAudit.client_request_id == client_request_id,
        )
    ).first()
    if audit is None:
        return None
    if audit.original_query != original_query or (
        requested_session_id is not None and audit.session_id != requested_session_id
    ):
        raise HTTPException(409, "Streaming request identifier was already used")

    chat = db.exec(
        select(ChatSession).where(
            ChatSession.id == audit.session_id,
            ChatSession.user_id == user.id,
            ChatSession.workspace_id == workspace_id,
        )
    ).first()
    assistant = db.exec(
        select(ChatMessage).where(
            ChatMessage.id == audit.assistant_message_id,
            ChatMessage.session_id == audit.session_id,
            ChatMessage.user_id == user.id,
            ChatMessage.role == "assistant",
        )
    ).first()
    if chat is None or assistant is None:
        raise HTTPException(409, "The saved streaming response is unavailable")

    return {
        "session_id": chat.id,
        "title": chat.title,
        "answer": assistant.content,
        "citations": audit.citation_map,
        "confidence": audit.answer_confidence or 0,
        "insufficient_evidence": audit.insufficient_evidence,
        "correlation_id": audit.tkp_correlation_id,
        "model": audit.answer_model,
        "request_id": client_request_id,
        "replayed": True,
    }


async def _prepare_streamed_tkp_turn(
    *,
    request: Request,
    db: Session,
    user: User,
    workspace_id: str,
    owned_chat: ChatSession | None,
    message: str,
    client_request_id: str,
    model: str,
) -> dict[str, object]:
    if user.id is None:
        raise RuntimeError("User persistence identifier is unavailable")
    user_id = user.id
    history = (
        _load_bounded_history(db, session_id=owned_chat.id, user_id=user_id)
        if owned_chat is not None and owned_chat.id is not None
        else BoundedConversationContext()
    )
    try:
        correlation_id = uuid.UUID(str(getattr(request.state, "correlation_id", "")))
    except ValueError:
        correlation_id = uuid.uuid4()
        request.state.correlation_id = str(correlation_id)

    tkp_client = getattr(request.app.state, "tkp_client", None)
    if not isinstance(tkp_client, TKPClient):
        raise GroundingError(
            code="TKP_NOT_CONFIGURED",
            public_message="Knowledge retrieval is not configured",
            status_code=503,
        )

    retrieval_request = None
    retrieval = None
    resolved_query = await resolve_conversation_query(
        query=message,
        context=history,
        model=model,
    )
    if not resolved_query.context_resolved:
        standalone_query: str = ""
        grounded = GroundedAnswer(
            answer=AMBIGUOUS_CONTEXT_MESSAGE,
            confidence=0,
            insufficient_evidence=True,
            insufficient_reason="AMBIGUOUS_CONTEXT",
        )
        validation_status = "AMBIGUOUS_CONTEXT"
    else:
        resolved_standalone_query = resolved_query.standalone_query
        if resolved_standalone_query is None:
            raise GroundingError(
                code="CONTEXT_REWRITE_INVALID",
                public_message="The follow-up question could not be resolved safely",
            )
        standalone_query = resolved_standalone_query
        retrieval_limit = min(max(env_int("TKP_CHAT_RETRIEVAL_LIMIT", 10), 1), 20)
        retrieval_request = TKPRetrievalRequest.from_browser(
            BrowserRetrievalRequest(query=standalone_query, limit=retrieval_limit)
        )
        retrieval = await tkp_client.search(retrieval_request, correlation_id)
        grounded = await generate_grounded_answer(
            query=standalone_query,
            retrieval=retrieval,
            model=model,
        )
        validation_status = (
            "INSUFFICIENT_EVIDENCE" if grounded.insufficient_evidence else "VALIDATED"
        )

    try:
        chat, created_new = _persist_tkp_turn(
            db,
            chat=owned_chat,
            user=user,
            workspace_id=workspace_id,
            original_query=message,
            standalone_query=standalone_query,
            history=history,
            retrieval_request=retrieval_request,
            retrieval=retrieval,
            grounded=grounded,
            model=model,
            validation_status=validation_status,
            client_request_id=client_request_id,
        )
    except IntegrityError:
        replay = _replay_stream_payload(
            db,
            user=user,
            workspace_id=workspace_id,
            client_request_id=client_request_id,
            original_query=message,
            requested_session_id=owned_chat.id if owned_chat is not None else None,
        )
        if replay is None:
            raise
        return replay

    log_event(
        "chat",
        {
            "user": user.email,
            "tier": _tier_name(user),
            "session_id": chat.id,
            "route": "tkp_grounded_stream",
            "context_mode": "tkp_approved",
            "model": model,
            "insufficient_evidence": grounded.insufficient_evidence,
            "citation_count": len(grounded.citations),
        },
    )
    return {
        "session_id": chat.id,
        "title": chat.title if created_new else None,
        "answer": grounded.answer,
        "citations": [item.model_dump(mode="json") for item in grounded.citations],
        "confidence": grounded.confidence,
        "insufficient_evidence": grounded.insufficient_evidence,
        "correlation_id": str(correlation_id),
        "model": model,
        "request_id": client_request_id,
        "replayed": False,
    }


async def _stream_tkp_events(
    *,
    request: Request,
    prepare: Callable[[], Awaitable[dict[str, object]]],
    request_id: str,
) -> AsyncIterator[str]:
    try:
        payload = await asyncio.wait_for(prepare(), timeout=_stream_timeout_seconds())
        if await request.is_disconnected():
            return
        event_id = 1
        for index, chunk in enumerate(_bounded_answer_chunks(str(payload["answer"]))):
            yield _sse_event(
                "answer",
                {"request_id": request_id, "index": index, "chunk": chunk},
                event_id,
            )
            event_id += 1
        yield _sse_event(
            "citations",
            {
                "request_id": request_id,
                "citations": payload["citations"],
            },
            event_id,
        )
        event_id += 1
        completion = {key: value for key, value in payload.items() if key != "answer"}
        yield _sse_event("complete", completion, event_id)
    except asyncio.CancelledError:
        raise
    except TKPClientError as exc:
        yield _sse_event(
            "error",
            {
                "request_id": request_id,
                "code": exc.code,
                "message": exc.public_message,
                "correlation_id": str(exc.correlation_id),
                "retryable": exc.retryable,
            },
            1,
        )
    except GroundingError as exc:
        yield _sse_event(
            "error",
            {
                "request_id": request_id,
                "code": exc.code,
                "message": exc.public_message,
                "retryable": exc.status_code >= 500,
            },
            1,
        )
    except TimeoutError:
        yield _sse_event(
            "error",
            {
                "request_id": request_id,
                "code": "STREAM_TIMEOUT",
                "message": "Verified answer generation timed out",
                "retryable": True,
            },
            1,
        )
    except HTTPException as exc:
        yield _sse_event(
            "error",
            {
                "request_id": request_id,
                "code": "STREAM_REQUEST_REJECTED",
                "message": str(exc.detail) if exc.status_code < 500 else "Request failed safely",
                "retryable": False,
            },
            1,
        )
    except Exception:
        logger.exception("tkp_chat_stream_failed")
        yield _sse_event(
            "error",
            {
                "request_id": request_id,
                "code": "STREAM_UNAVAILABLE",
                "message": "Verified answer streaming is temporarily unavailable",
                "retryable": True,
            },
            1,
        )


# =========================
# Read endpoints
# =========================
@router.post("/stream")
@limiter.limit("20/minute;300/hour")
async def stream_answer(
    request: Request,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> StreamingResponse:
    if env("ORGANIZATIONAL_RAG_MODE", "legacy").lower() != "tkp":
        raise HTTPException(409, "Grounded streaming requires the TKP knowledge mode")

    try:
        payload = StreamChatIn.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, "A message and request identifier are required") from exc

    message = sanitize_user_input(payload.message)
    if not message:
        raise HTTPException(422, "message is required")
    user = db.exec(select(User).where(User.email == user_email)).first()
    if user is None or user.id is None:
        raise HTTPException(401, "User not found")

    try:
        tkp_settings = get_tkp_settings()
    except ValidationError as exc:
        raise HTTPException(503, "Knowledge retrieval is not configured") from exc
    access = require_tkp_workspace_access(user=user, db=db, settings=tkp_settings)
    workspace_id = str(access.workspace_id)

    owned_chat = None
    if payload.session_id is not None:
        owned_chat = require_owned_chat_session(
            db,
            session_id=payload.session_id,
            user_id=user.id,
        )
        if owned_chat.workspace_id != workspace_id:
            raise HTTPException(404, "Chat not found")

    request_id = str(payload.request_id)
    replay = _replay_stream_payload(
        db,
        user=user,
        workspace_id=workspace_id,
        client_request_id=request_id,
        original_query=message,
        requested_session_id=payload.session_id,
    )
    if replay is None:
        tier = _tier_name(user)
        limit = plan_limit(tier)
        if limit not in (-1, None) and _today_user_chat_count(db, user.id) >= limit:
            raise HTTPException(429, f"Daily chat limit reached ({limit}/day)")
        model = plan_model(tier)

        async def prepare() -> dict[str, object]:
            return await _prepare_streamed_tkp_turn(
                request=request,
                db=db,
                user=user,
                workspace_id=workspace_id,
                owned_chat=owned_chat,
                message=message,
                client_request_id=request_id,
                model=model,
            )

    else:

        async def prepare() -> dict[str, object]:
            return replay

    return StreamingResponse(
        _stream_tkp_events(
            request=request,
            prepare=prepare,
            request_id=request_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/sessions", response_model=List[ChatSessionOut])
def get_sessions(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        return []
    statement = select(ChatSession).where(ChatSession.user_id == user.id)
    workspace_id = _authorized_tkp_workspace_id(user=user, db=db)
    if workspace_id is not None:
        statement = statement.where(ChatSession.workspace_id == workspace_id)
    return db.exec(statement.order_by(ChatSession.created_at.desc())).all()


@router.get("/{session_id}", response_model=List[ChatMessageOut])
def get_messages(
    session_id: int,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if user is None or user.id is None:
        raise HTTPException(401, "User not found")
    chat = require_owned_chat_session(db, session_id=session_id, user_id=user.id)
    workspace_id = _authorized_tkp_workspace_id(user=user, db=db)
    if workspace_id is not None and chat.workspace_id != workspace_id:
        raise HTTPException(404, "Chat not found")
    messages = db.exec(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.user_id == user.id,
        )
        .order_by(ChatMessage.id)
    ).all()
    assistant_ids = [
        message.id
        for message in messages
        if message.id is not None and message.role == "assistant"
    ]
    citations_by_message: dict[int, list[dict[str, object]]] = {}
    if assistant_ids and workspace_id is not None:
        audits = db.exec(
            select(AnswerEvidenceAudit).where(
                AnswerEvidenceAudit.session_id == session_id,
                AnswerEvidenceAudit.user_id == user.id,
                AnswerEvidenceAudit.workspace_id == workspace_id,
                col(AnswerEvidenceAudit.assistant_message_id).in_(assistant_ids),
            )
        ).all()
        citations_by_message = {
            audit.assistant_message_id: audit.citation_map for audit in audits
        }
    return [
        ChatMessageOut(
            role=message.role,
            content=message.content,
            citations=citations_by_message.get(message.id or -1, []),
        )
        for message in messages
    ]


@router.patch("/{session_id}/title")
def rename_session(
    session_id: int,
    payload: RenameIn,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(401, "User not found")

    chat = require_owned_chat_session(db, session_id=session_id, user_id=user.id)
    workspace_id = _authorized_tkp_workspace_id(user=user, db=db)
    if workspace_id is not None and chat.workspace_id != workspace_id:
        raise HTTPException(404, "Chat not found")

    chat.title = payload.title.strip()[:80] or "Untitled"
    db.add(chat)
    db.commit()
    return {"ok": True, "title": chat.title}


# =========================
# ASK ENDPOINT (Final)
# =========================
@router.post("")
@limiter.limit("20/minute;300/hour")
async def ask(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    tkp_mode = env("ORGANIZATIONAL_RAG_MODE", "legacy").lower() == "tkp"
    try:
        body = await request.json()
    except Exception:
        body = {}

    raw_message = (
        body.get("message")
        or body.get("payload")
        or (body.get("query") or {}).get("payload")
        or ""
    )

    message = sanitize_user_input(raw_message)
    if not message:
        raise HTTPException(422, "message is required")

    raw_sid = body.get("session_id")
    try:
        session_id: Optional[int] = int(raw_sid) if raw_sid is not None else None
    except Exception:
        session_id = None

    # ---------- Auth / Plan ----------
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(401, "User not found")

    tier = _tier_name(user)

    limit = plan_limit(tier)
    if limit not in (-1, None):
        if _today_user_chat_count(db, user.id) >= limit:
            raise HTTPException(429, f"Daily chat limit reached ({limit}/day)")

    owned_chat = None
    if session_id is not None:
        owned_chat = require_owned_chat_session(db, session_id=session_id, user_id=user.id)

    if tkp_mode:
        try:
            tkp_settings = get_tkp_settings()
        except ValidationError:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "TKP_NOT_CONFIGURED",
                    "message": "Knowledge retrieval is not configured",
                    "details": None,
                },
            )
        access = require_tkp_workspace_access(user=user, db=db, settings=tkp_settings)
        workspace_id = str(access.workspace_id)
        if owned_chat is not None and owned_chat.workspace_id != workspace_id:
            # Null and foreign workspace bindings are both unusable in the trusted TKP lane.
            raise HTTPException(status_code=404, detail="Chat not found")

        history = (
            _load_bounded_history(db, session_id=owned_chat.id, user_id=user.id)
            if owned_chat is not None and owned_chat.id is not None
            else BoundedConversationContext()
        )

        try:
            correlation_id = uuid.UUID(str(getattr(request.state, "correlation_id", "")))
        except ValueError:
            correlation_id = uuid.uuid4()
            request.state.correlation_id = str(correlation_id)

        tkp_client = getattr(request.app.state, "tkp_client", None)
        if not isinstance(tkp_client, TKPClient):
            return JSONResponse(
                status_code=503,
                content={
                    "code": "TKP_NOT_CONFIGURED",
                    "message": "Knowledge retrieval is not configured",
                    "correlation_id": str(correlation_id),
                    "details": None,
                },
                headers={"X-Correlation-ID": str(correlation_id)},
            )

        model = plan_model(tier)
        retrieval_limit = min(max(env_int("TKP_CHAT_RETRIEVAL_LIMIT", 10), 1), 20)
        retrieval_request = None
        retrieval = None
        try:
            resolved_query = await resolve_conversation_query(
                query=message,
                context=history,
                model=model,
            )
            if not resolved_query.context_resolved:
                grounded = GroundedAnswer(
                    answer=AMBIGUOUS_CONTEXT_MESSAGE,
                    confidence=0,
                    insufficient_evidence=True,
                    insufficient_reason="AMBIGUOUS_CONTEXT",
                )
                chat, created_new = _persist_tkp_turn(
                    db,
                    chat=owned_chat,
                    user=user,
                    workspace_id=workspace_id,
                    original_query=message,
                    standalone_query="",
                    history=history,
                    retrieval_request=None,
                    retrieval=None,
                    grounded=grounded,
                    model=model,
                    validation_status="AMBIGUOUS_CONTEXT",
                )
                payload = {
                    "ok": True,
                    "session_id": chat.id,
                    "response": grounded.answer,
                    "answer": grounded.answer,
                    "route": "tkp_grounded",
                    "context_mode": "tkp_approved",
                    "source": "tkp",
                    "model": model,
                    "confidence": 0,
                    "insufficient_evidence": True,
                    "citations": [],
                    "correlation_id": str(correlation_id),
                }
                if created_new:
                    payload["title"] = _title_from_text(message)
                return payload

            standalone_query = resolved_query.standalone_query
            if standalone_query is None:
                raise GroundingError(
                    code="CONTEXT_REWRITE_INVALID",
                    public_message="The follow-up question could not be resolved safely",
                )
            retrieval_request = TKPRetrievalRequest.from_browser(
                BrowserRetrievalRequest(query=standalone_query, limit=retrieval_limit)
            )
            retrieval = await tkp_client.search(
                retrieval_request,
                correlation_id,
            )
            grounded = await generate_grounded_answer(
                query=standalone_query,
                retrieval=retrieval,
                model=model,
            )
        except asyncio.CancelledError:
            raise
        except TKPClientError as exc:
            logger.warning(
                "tkp_chat_retrieval_failed",
                extra={
                    "code": exc.code,
                    "correlation_id": str(exc.correlation_id),
                    "upstream_status": exc.upstream_status,
                    "user_id": user.id,
                    "workspace_id": str(access.workspace_id),
                },
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": exc.code,
                    "message": exc.public_message,
                    "correlation_id": str(exc.correlation_id),
                    "details": None,
                },
                headers={"X-Correlation-ID": str(exc.correlation_id)},
            )
        except GroundingError as exc:
            logger.warning(
                "tkp_chat_grounding_rejected",
                extra={
                    "code": exc.code,
                    "correlation_id": str(correlation_id),
                    "user_id": user.id,
                    "workspace_id": str(access.workspace_id),
                },
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": exc.code,
                    "message": exc.public_message,
                    "correlation_id": str(correlation_id),
                    "details": None,
                },
                headers={"X-Correlation-ID": str(correlation_id)},
            )

        validation_status = (
            "INSUFFICIENT_EVIDENCE" if grounded.insufficient_evidence else "VALIDATED"
        )
        chat, created_new = _persist_tkp_turn(
            db,
            chat=owned_chat,
            user=user,
            workspace_id=workspace_id,
            original_query=message,
            standalone_query=standalone_query,
            history=history,
            retrieval_request=retrieval_request,
            retrieval=retrieval,
            grounded=grounded,
            model=model,
            validation_status=validation_status,
        )
        session_id = chat.id

        log_event(
            "chat",
            {
                "user": user_email,
                "tier": tier,
                "session_id": session_id,
                "route": "tkp_grounded",
                "context_mode": "tkp_approved",
                "model": model,
                "insufficient_evidence": grounded.insufficient_evidence,
                "citation_count": len(grounded.citations),
            },
        )
        payload = {
            "ok": True,
            "session_id": session_id,
            "response": grounded.answer,
            "answer": grounded.answer,
            "route": "tkp_grounded",
            "context_mode": "tkp_approved",
            "source": "tkp",
            "model": model,
            "confidence": grounded.confidence,
            "insufficient_evidence": grounded.insufficient_evidence,
            "citations": [
                citation.model_dump(mode="json") for citation in grounded.citations
            ],
            "correlation_id": str(correlation_id),
        }
        if created_new:
            payload["title"] = _title_from_text(message)
        return payload

    # ---------- Session ----------
    created_new = False
    if not session_id:
        chat = ChatSession(user_id=user.id, title=_title_from_text(message))
        db.add(chat)
        db.commit()
        db.refresh(chat)
        session_id = chat.id
        created_new = True

    session_uuid = _session_uuid(session_id)
    msg_index = _messages_in_session(db, session_id)

    # ---------- OpenAI ----------
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = plan_model(tier)

    # ---------- ROUTER ----------
    router_prompt = env("ROUTER_PROMPT").format(
        query=message,
        has_docs=True,
    )

    try:
        route = client.chat.completions.create(
            model=env("OPENAI_MODEL_PREPROC", "gpt-4o-mini"),
            messages=[{"role": "system", "content": router_prompt}],
            temperature=0,
            max_tokens=5,
        ).choices[0].message.content.strip().lower()
    except Exception:
        route = "hybrid"

    if route not in ("rag_only", "llm_only", "hybrid"):
        route = "hybrid"

    # ---------- RETRIEVAL ----------
    context_text = ""
    docs = []

    if route in ("rag_only", "hybrid"):
        try:
            docs = query_user_docs(
                user_email,
                message,
                top_k=env_int("SEARCH_TOPK_PRO", 8),
            )
        except Exception:
            docs = []

        context_text = "\n\n".join(d.page_content for d in docs)

        if route == "rag_only" and not context_text:
            route = "llm_only"

    # ---------- REASONING ----------
    analysis = ""
    if route == "llm_only" or (route == "hybrid" and context_text):
        try:
            reasoning_prompt = f"{env('REASONING_PROMPT')}\n\nQuery:\n{message}"
            analysis = client.chat.completions.create(
                model=env("OPENAI_MODEL_PREPROC", "gpt-4o-mini"),
                messages=[{"role": "system", "content": reasoning_prompt}],
                temperature=0,
                max_tokens=300,
            ).choices[0].message.content
        except Exception:
            analysis = ""

    guard = env("PROMPT_SAFETY_GUARD")

    # ---------- SYSTEM PROMPT ----------
    if route == "rag_only":
        context_mode, source = "docs_only", "docs"
        system_prompt = (
            f"{env('PROMPT_DOCS_ONLY')}\n\n"
            f"Document Context:\n{context_text}\n\n{guard}"
        )
    elif route == "llm_only":
        context_mode, source = "external", "gpt"
        system_prompt = (
            f"{env('PROMPT_LLM_ONLY')}\n\n"
            f"Reasoning Notes:\n{analysis}\n\n{guard}"
        )
    else:
        context_mode, source = "hybrid", "docs+gpt"
        system_prompt = (
            f"{env('PROMPT_HYBRID')}\n\n"
            f"Document Context:\n{context_text}\n\n"
            f"Reasoning Notes:\n{analysis}\n\n{guard}"
        )

    # ---------- FINAL ANSWER ----------
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": wrap_user_content(message)},
            ],
            temperature=0.2,
        )
        ai_text = resp.choices[0].message.content.strip()
    except Exception:
        logger.exception("chat_generation_failed")
        raise HTTPException(503, "Chat generation is temporarily unavailable") from None

    # ---------- STORE ----------
    now = datetime.utcnow()
    db.add(ChatMessage(session_id=session_id, user_id=user.id, role="user", content=message, created_at=now))
    db.add(ChatMessage(session_id=session_id, user_id=user.id, role="assistant", content=ai_text, created_at=now))
    db.commit()

    log_event("chat", {
        "user": user_email,
        "tier": tier,
        "session_id": session_id,
        "route": route,
        "context_mode": context_mode,
        "model": model,
    })

    payload = {
        "ok": True,
        "session_id": session_id,
        "response": ai_text,
        "route": route,
        "context_mode": context_mode,
        "source": source,
        "model": model,
    }
    if created_new:
        payload["title"] = _title_from_text(message)

    return payload


# # app/routes/chat.py
# from __future__ import annotations

# import os, time, uuid, asyncio, traceback
# from typing import Optional, List, Tuple, Any, Dict, Literal
# from datetime import datetime, date, timedelta
# from contextlib import asynccontextmanager

# from fastapi import APIRouter, Depends, HTTPException, Request, Response
# from fastapi.responses import JSONResponse
# from pydantic import BaseModel
# from sqlmodel import Session, select, func
# from openai import OpenAI, OpenAIError

# from app.db import get_session
# from app.models import ChatSession, ChatMessage, User
# from app.schemas import ChatSessionOut, ChatMessageOut
# from app.deps.auth import get_current_user
# from app.utils.logger import log_event
# from app.vector_store import query_user_docs

# # Optional OpenTelemetry
# try:
#     from opentelemetry import trace
#     _otel_tracer = trace.get_tracer(__name__)
# except Exception:
#     trace = None
#     _otel_tracer = None

# # Plans / policy
# from app.config.plan_policy import (
#     plan_limit,
#     plan_model,
#     is_session_scoped,
#     plan_for,
#     caps_for,
# )

# # Optional LLM usage logger
# from app.utils.llm_logger import log_llm_event

# # Rate limiting
# from app.rate_limit import  key_user_or_ip

# # Analytics recorder
# from app.analytics.deps import chat_event_recorder


# router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# # ----------------------------- Models -----------------------------
# class ChatIn(BaseModel):
#     message: str
#     session_id: Optional[int] = None
#     mode: Literal["qa"] = "qa"


# class RenameIn(BaseModel):
#     title: str


# ChatIn.model_rebuild()
# RenameIn.model_rebuild()


# # ----------------------------- Helpers -----------------------------
# def _tier_name(user: Any) -> str:
#     return plan_for(user).name


# def _title_from_text(text: str) -> str:
#     if not text:
#         return "New Chat"
#     s = " ".join(text.strip().split())
#     return (s[:60] + "…") if len(s) > 60 else s


# def _today_user_chat_count(db: Session, user_id: int) -> int:
#     start = datetime.combine(date.today(), datetime.min.time())
#     end = datetime.combine(date.today(), datetime.max.time())
#     return db.exec(
#         select(func.count(ChatMessage.id)).where(
#             ChatMessage.user_id == user_id,
#             ChatMessage.role == "user",
#             ChatMessage.created_at >= start,
#             ChatMessage.created_at <= end,
#         )
#     ).one()


# def _plan_rate_windows_for(tier: str) -> Tuple[int, int]:
#     t = (tier or "").strip().lower()
#     env_min = os.getenv(f"PLAN_CHAT_RPM_{t.upper()}", None)
#     env_hr = os.getenv(f"PLAN_CHAT_RPH_{t.upper()}", None)
#     caps = caps_for(tier)
#     rpm = int(env_min) if env_min else caps.rpm_limit
#     rph = int(env_hr) if env_hr else caps.rph_limit
#     return rpm, rph


# def _enforce_plan_rps(db: Session, user_id: int, tier: str) -> None:
#     per_min, per_hour = _plan_rate_windows_for(tier or "free")
#     now = datetime.utcnow()
#     one_min_ago = now - timedelta(minutes=1)
#     one_hr_ago = now - timedelta(hours=1)
#     used_min = db.exec(
#         select(func.count(ChatMessage.id)).where(
#             ChatMessage.user_id == user_id,
#             ChatMessage.role == "user",
#             ChatMessage.created_at >= one_min_ago,
#         )
#     ).one()
#     used_hr = db.exec(
#         select(func.count(ChatMessage.id)).where(
#             ChatMessage.user_id == user_id,
#             ChatMessage.role == "user",
#             ChatMessage.created_at >= one_hr_ago,
#         )
#     ).one()
#     if used_min >= per_min:
#         raise HTTPException(429, f"Per-minute chat limit reached ({per_min}/minute).")
#     if used_hr >= per_hour:
#         raise HTTPException(429, f"Per-hour chat limit reached ({per_hour}/hour).")


# @asynccontextmanager
# async def _maybe_bucket(request: Request, key: str):
#     mgr = getattr(getattr(request.app, "state", object()), "llm_concurrency", None)
#     if hasattr(mgr, "bucket"):
#         sem = mgr.bucket(key)
#         async with sem:
#             yield
#     else:
#         yield


# def _session_int_to_uuid(session_id: int) -> uuid.UUID:
#     return uuid.uuid5(uuid.NAMESPACE_URL, f"chat-session:{session_id}")


# def _messages_in_session(db: Session, session_id: int) -> int:
#     return db.exec(
#         select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
#     ).one()


# # ----------------------------- Read Endpoints -----------------------------
# @router.get("/sessions", response_model=List[ChatSessionOut])
# # @limiter.limit("60/minute", key_func=key_user_or_ip)
# def get_sessions(
#     request: Request,
#     response: Response,
#     user_email: str = Depends(get_current_user),
#     db: Session = Depends(get_session),
# ):
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         return []
#     return db.exec(
#         select(ChatSession)
#         .where(ChatSession.user_id == user.id)
#         .order_by(ChatSession.created_at.desc())
#     ).all()


# @router.get("/{session_id}", response_model=List[ChatMessageOut])
# # @limiter.limit("60/minute", key_func=key_user_or_ip)
# def get_chat_messages(
#     request: Request,
#     response: Response,
#     session_id: int,
#     db: Session = Depends(get_session),
# ):
#     return db.exec(
#         select(ChatMessage)
#         .where(ChatMessage.session_id == session_id)
#         .order_by(ChatMessage.id)
#     ).all()


# @router.patch("/{session_id}/title")
# # @limiter.limit("15/minute;200/hour", key_func=key_user_or_ip)
# def rename_chat_session(
#     request: Request,
#     response: Response,
#     session_id: int,
#     payload: Dict[str, str],
#     db: Session = Depends(get_session),
#     user_email: str = Depends(get_current_user),
# ):
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(401, "User not found")
#     chat = db.exec(
#         select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
#     ).first()
#     if not chat:
#         raise HTTPException(404, "Chat not found")
#     chat.title = (" ".join((payload.get("title") or "").split()))[:80] or "Untitled"
#     db.add(chat)
#     db.commit()
#     return {"ok": True, "title": chat.title}


# # ----------------------------- Ask Endpoint -----------------------------
# # @router.post("")
# # async def ask(
# #     request: Request,
# #     response: Response,
# #     db: Session = Depends(get_session),
# #     user_email: str = Depends(get_current_user),
# # ):
# #     try:
# #         body: Dict[str, Any] = await request.json()
# #     except Exception:
# #         body = {}

# #     message = (
# #         (body.get("message") or body.get("payload") or (body.get("query") or {}).get("payload") or "")
# #     ).strip()
# #     if not message:
# #         raise HTTPException(422, "message/payload is required")

# #     raw_sid = body.get("session_id")
# #     try:
# #         session_id: Optional[int] = int(raw_sid) if raw_sid is not None else None
# #     except (TypeError, ValueError):
# #         session_id = None

# #     # --- Auth & plan enforcement ---
# #     user = db.exec(select(User).where(User.email == user_email)).first()
# #     if not user:
# #         raise HTTPException(401, "User not found")

# #     tier = _tier_name(user)
# #     caps = caps_for(tier)
# #     _enforce_plan_rps(db, user.id, tier)

# #     limit = plan_limit(tier)
# #     if limit not in (-1, None):
# #         used = _today_user_chat_count(db, user.id)
# #         if used >= limit:
# #             raise HTTPException(429, f"Daily chat limit reached ({limit}/day)")

# #     # --- Ensure session ---
# #     created_new_session = False
# #     if not session_id:
# #         new_s = ChatSession(user_id=user.id, title=_title_from_text(message))
# #         db.add(new_s)
# #         db.commit()
# #         db.refresh(new_s)
# #         session_id = new_s.id
# #         created_new_session = True

# #     msg_index = _messages_in_session(db, session_id)
# #     sess_scoped = is_session_scoped(tier)
# #     scope = {"session_id": str(session_id), "session_scoped_only": sess_scoped}

# #     session_uuid = _session_int_to_uuid(session_id)
# #     key = key_user_or_ip(request)
# #     model = plan_model(tier)

# #     # Ensure API key present
# #     api_key = os.getenv("OPENAI_API_KEY")
# #     if not api_key:
# #         raise HTTPException(500, "OpenAI API key not configured")
# #     client = OpenAI(api_key=api_key)

# #     # ---------------- Context Retrieval ----------------
# #     try:
# #         docs = query_user_docs(user_email, message, top_k=4)
# #     except Exception as e:
# #         docs, context_mode = [], "none"
# #         print("Vector search failed:", e)

# #     def _context_quality(docs: List[Any]) -> Tuple[str, float, int]:
# #         if not docs:
# #             return "", 0.0, 0
# #         total_score = sum(getattr(d, "score", 0.0) for d in docs)
# #         avg_score = total_score / len(docs)
# #         text = "\n\n".join([getattr(d, "page_content", "") for d in docs])
# #         return text, avg_score, len(docs)

# #     context_text, avg_score, chunk_count = _context_quality(docs)
# #     context_len = len(context_text)

# #     # Decision logic: Docs-only / Hybrid / External
# #     if context_len > 1000 and avg_score > 0.75 and chunk_count >= 2:
# #         context_mode = "docs_only"
# #         system_prompt = (
# #             "You are an OpenText consultant assistant. "
# #             "Use ONLY the provided document context to answer accurately. "
# #             "Do not include external details unless clarification is required.\n\n"
# #             f"Context:\n{context_text}\n\n"
# #         )
# #         source = "docs"

# #     elif context_len > 300 and avg_score > 0.4:
# #         context_mode = "hybrid"
# #         system_prompt = (
# #             "You are an OpenText domain expert. The following partial context is from "
# #             "uploaded documents. Use it as your base but enrich with relevant verified "
# #             "knowledge or OpenText configuration practices to make the response complete.\n\n"
# #             f"Context:\n{context_text}\n\n"
# #         )
# #         source = "docs+gpt"

# #     else:
# #         context_mode = "external"
# #         system_prompt = (
# #             "You are an OpenText product expert. No relevant internal context found. "
# #             "Respond using your broader understanding of OpenText systems, architecture, "
# #             "and best practices. Provide a comprehensive, technically accurate answer."
# #         )
# #         source = "gpt"

# #     # ---------------- LLM Call ----------------
# #     with chat_event_recorder(
# #         request=request,
# #         db=db,
# #         user_id=user.email,
# #         plan=tier,
# #         chat_session_id=session_uuid,
# #         message_index=msg_index,
# #         model=model,
# #         provider="openai",
# #         intent="qa",
# #         pipeline_version="v3",
# #     ):
# #         latency_start = time.perf_counter()
# #         try:
# #             supports_temp = not any(x in model.lower() for x in ["gpt-5", "o1", "o3"])
# #             chat_args = {
# #                 "model": model,
# #                 "messages": [
# #                     {"role": "system", "content": system_prompt},
# #                     {"role": "user", "content": message},
# #                 ],
# #             }
# #             if supports_temp:
# #                 chat_args["temperature"] = float(os.getenv("CHAT_TEMPERATURE", "0.2"))

# #             resp = client.chat.completions.create(**chat_args)
# #             ai_text = resp.choices[0].message.content.strip()
# #             took_ms = int((time.perf_counter() - latency_start) * 1000)
# #             request.state.response_code = 200
# #         except OpenAIError as e:
# #             print("OpenAIError:", traceback.format_exc())
# #             raise HTTPException(500, f"OpenAI API error: {e}")
# #         except Exception as e:
# #             print("LLM Exception:", traceback.format_exc())
# #             raise HTTPException(500, f"Chat generation failed: {e}")

# #     # ---------------- Persist Messages ----------------
# #     now = datetime.utcnow()
# #     db.add(ChatMessage(session_id=session_id, user_id=user.id, role="user", content=message, created_at=now))
# #     db.add(ChatMessage(session_id=session_id, user_id=user.id, role="assistant", content=ai_text, created_at=now))
# #     db.commit()

# #     try:
# #         log_llm_event(
# #             db=db,
# #             user_id=user.id,
# #             tier=tier,
# #             model=model,
# #             provider="openai",
# #             request_tokens=0,
# #             response_tokens=0,
# #             latency_ms=0,
# #             chat_session_id=session_id,
# #         )
# #     except Exception as e:
# #         print("LLM log error:", e)

# #     log_event("chat", {
# #         "user": user_email,
# #         "tier": tier,
# #         "session_id": session_id,
# #         "source": source,
# #         "context_mode": context_mode,
# #         "model": model,
# #         "query": message,
# #     })

# #     payload = {
# #         "ok": True,
# #         "session_id": session_id,
# #         "response": ai_text,
# #         "source": source,
# #         "context_mode": context_mode,
# #         "model": model,
# #     }
# #     if created_new_session:
# #         payload["title"] = _title_from_text(message)
# #     return payload
# # ---------------- Router for Query Classification ----------------
# ROUTER_PROMPT = """
# You are a routing model that decides how a query should be answered.

# Output ONLY one label: "rag_only", "llm_only", or "hybrid".

# Definitions:
# - rag_only: Answer MUST rely on retrieved documents.
# - llm_only: No retrieval needed; use general reasoning.
# - hybrid: Retrieve documents AND apply reasoning.

# Now classify this query:
# {query}
# """

# def classify_query(query: str, client: OpenAI) -> str:
#     try:
#         resp = client.chat.completions.create(
#             model="gpt-4.1-mini",
#             messages=[{"role": "system", "content": ROUTER_PROMPT.format(query=query)}],
#             max_tokens=5,
#             temperature=0,
#         )
#         label = resp.choices[0].message["content"].strip().lower()
#         if label not in ["rag_only", "llm_only", "hybrid"]:
#             return "hybrid"
#         return label
#     except Exception:
#         return "hybrid"



# # ----------------------------- ASK ENDPOINT -----------------------------
# # @router.post("")
# # async def ask(
# #     request: Request,
# #     response: Response,
# #     db: Session = Depends(get_session),
# #     user_email: str = Depends(get_current_user),
# # ):
# #     try:
# #         body: Dict[str, Any] = await request.json()
# #     except Exception:
# #         body = {}

# #     message = (
# #         (body.get("message") or body.get("payload") or (body.get("query") or {}).get("payload") or "")
# #     ).strip()
# #     if not message:
# #         raise HTTPException(422, "message/payload is required")

# #     raw_sid = body.get("session_id")
# #     try:
# #         session_id: Optional[int] = int(raw_sid) if raw_sid is not None else None
# #     except (TypeError, ValueError):
# #         session_id = None


# #     # --- Auth & plan enforcement ---
# #     user = db.exec(select(User).where(User.email == user_email)).first()
# #     if not user:
# #         raise HTTPException(401, "User not found")

# #     tier = _tier_name(user)
# #     caps = caps_for(tier)
# #     _enforce_plan_rps(db, user.id, tier)

# #     limit = plan_limit(tier)
# #     if limit not in (-1, None):
# #         used = _today_user_chat_count(db, user.id)
# #         if used >= limit:
# #             raise HTTPException(429, f"Daily chat limit reached ({limit}/day)")


# #     # --- Ensure chat session ---
# #     created_new_session = False
# #     if not session_id:
# #         new_s = ChatSession(user_id=user.id, title=_title_from_text(message))
# #         db.add(new_s)
# #         db.commit()
# #         db.refresh(new_s)
# #         session_id = new_s.id
# #         created_new_session = True

# #     msg_index = _messages_in_session(db, session_id)
# #     sess_scoped = is_session_scoped(tier)
# #     scope = {"session_id": str(session_id), "session_scoped_only": sess_scoped}

# #     session_uuid = _session_int_to_uuid(session_id)
# #     key = key_user_or_ip(request)
# #     model = plan_model(tier)

# #     # --- Ensure API key ---
# #     api_key = os.getenv("OPENAI_API_KEY")
# #     if not api_key:
# #         raise HTTPException(500, "OpenAI API key not configured")
# #     client = OpenAI(api_key=api_key)


# #     # -------------- STEP 1: ROUTE QUERY ----------------
# #     try:
# #         route = classify_query(message, client)
# #     except Exception:
# #         route = "hybrid"

# #     print("ROUTER DECISION:", route)


# #     # -------------- STEP 2: CONDITIONAL RETRIEVAL --------------
# #     docs = []
# #     context_text = ""

# #     if route in ("rag_only", "hybrid"):
# #         try:
# #             docs = query_user_docs(user_email, message, top_k=4)
# #         except Exception as e:
# #             print("Vector search failed:", e)
# #             docs = []

# #         context_text = "\n\n".join([getattr(d, "page_content", "") for d in docs])


# #     # -------------- STEP 3: CONDITIONAL REASONING (GPT-5) --------------
# #     analysis = ""
# #     if route in ("llm_only", "hybrid"):
# #         try:
# #             reasoning_prompt = f"""
# #             Provide reasoning notes for this user query. 
# #             Do NOT answer the question completely. 
# #             Provide only high-level reasoning and background thoughts:

# #             Query:
# #             {message}
# #             """
# #             analysis = client.chat.completions.create(
# #                 model="gpt-5-mini",
# #                 messages=[{"role": "system", "content": reasoning_prompt}],
# #                 max_tokens=300,
# #                 temperature=0,
# #             ).choices[0].message.content
# #         except Exception as e:
# #             analysis = ""


# #     # -------------- STEP 4: SYNTHESIS — BUILD SYSTEM PROMPT --------------
# #     if route == "rag_only":
# #         context_mode = "docs_only"
# #         source = "docs"
# #         system_prompt = (
# #             "You MUST answer using ONLY the retrieved documents.\n\n"
# #             f"Document Context:\n{context_text}"
# #         )

# #     elif route == "llm_only":
# #         context_mode = "external"
# #         source = "gpt"
# #         system_prompt = (
# #             "No document context is required. Use general reasoning.\n\n"
# #             f"Reasoning Notes:\n{analysis}"
# #         )

# #     else:  # hybrid
# #         context_mode = "hybrid"
# #         source = "docs+gpt"
# #         system_prompt = (
# #             "Combine retrieved documents with additional reasoning.\n\n"
# #             f"Document Context:\n{context_text}\n\n"
# #             f"Reasoning Notes:\n{analysis}\n\n"
# #             "Prioritize document facts; fill gaps using reasoning."
# #         )


# #     # -------------- STEP 5: MAIN LLM CALL (GPT-5 or plan model) --------------
# #     with chat_event_recorder(
# #         request=request,
# #         db=db,
# #         user_id=user.email,
# #         plan=tier,
# #         chat_session_id=session_uuid,
# #         message_index=msg_index,
# #         model=model,
# #         provider="openai",
# #         intent="qa",
# #         pipeline_version="v4",
# #     ):

# #         latency_start = time.perf_counter()

# #         try:
# #             supports_temp = not any(x in model.lower() for x in ["gpt-5", "o1", "o3"])

# #             chat_args = {
# #                 "model": model,
# #                 "messages": [
# #                     {"role": "system", "content": system_prompt},
# #                     {"role": "user", "content": message},
# #                 ],
# #             }

# #             if supports_temp:
# #                 chat_args["temperature"] = float(os.getenv("CHAT_TEMPERATURE", "0.2"))

# #             resp = client.chat.completions.create(**chat_args)
# #             ai_text = resp.choices[0].message.content.strip()
# #         except Exception as e:
# #             raise HTTPException(500, f"Chat generation failed: {e}")


# #     # -------------- PERSIST MESSAGES --------------
# #     now = datetime.utcnow()
# #     db.add(ChatMessage(session_id=session_id, user_id=user.id, role="user", content=message, created_at=now))
# #     db.add(ChatMessage(session_id=session_id, user_id=user.id, role="assistant", content=ai_text, created_at=now))
# #     db.commit()


# #     # -------------- LOG EVENTS --------------
# #     try:
# #         log_llm_event(
# #             db=db,
# #             user_id=user.id,
# #             tier=tier,
# #             model=model,
# #             provider="openai",
# #             request_tokens=0,
# #             response_tokens=0,
# #             latency_ms=0,
# #             chat_session_id=session_id,
# #         )
# #     except Exception as e:
# #         print("LLM log error:", e)


# #     log_event("chat", {
# #         "user": user_email,
# #         "tier": tier,
# #         "session_id": session_id,
# #         "source": source,
# #         "context_mode": context_mode,
# #         "model": model,
# #         "query": message,
# #         "route": route,
# #     })


# #     payload = {
# #         "ok": True,
# #         "session_id": session_id,
# #         "response": ai_text,
# #         "source": source,
# #         "context_mode": context_mode,
# #         "route": route,
# #         "model": model,
# #     }
# #     if created_new_session:
# #         payload["title"] = _title_from_text(message)

# #     return payload
# @router.post("")
# async def ask(
#     request: Request,
#     response: Response,
#     db: Session = Depends(get_session),
#     user_email: str = Depends(get_current_user),
# ):
#     import re

#     def env(name: str, default: str = "") -> str:
#         return (os.getenv(name, default) or "").strip()

#     def sanitize_user_input(text: str) -> str:
#         text = re.sub(r"<[^>]+>", "", text)     # strip HTML / scripts
#         text = re.sub(r"\s+", " ", text)        # normalize whitespace
#         return text.strip()

#     def wrap_user_content(text: str) -> str:
#         return f"USER_CONTENT_START\n{text}\nUSER_CONTENT_END"

#     # ---------- READ BODY ----------
#     try:
#         body: Dict[str, Any] = await request.json()
#     except Exception:
#         body = {}

#     raw_message = (
#         body.get("message")
#         or body.get("payload")
#         or (body.get("query") or {}).get("payload")
#         or ""
#     )

#     message = sanitize_user_input(raw_message)
#     if not message:
#         raise HTTPException(422, "message/payload is required")

#     raw_sid = body.get("session_id")
#     try:
#         session_id: Optional[int] = int(raw_sid) if raw_sid is not None else None
#     except (TypeError, ValueError):
#         session_id = None

#     # ---------- AUTH / PLAN ----------
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(401, "User not found")

#     tier = _tier_name(user)
#     _enforce_plan_rps(db, user.id, tier)

#     limit = plan_limit(tier)
#     if limit not in (-1, None):
#         if _today_user_chat_count(db, user.id) >= limit:
#             raise HTTPException(429, f"Daily chat limit reached ({limit}/day)")

#     # ---------- SESSION ----------
#     created_new_session = False
#     if not session_id:
#         chat = ChatSession(user_id=user.id, title=_title_from_text(message))
#         db.add(chat)
#         db.commit()
#         db.refresh(chat)
#         session_id = chat.id
#         created_new_session = True

#     msg_index = _messages_in_session(db, session_id)
#     session_uuid = _session_int_to_uuid(session_id)
#     model = plan_model(tier)

#     # ---------- OPENAI ----------
#     api_key = os.getenv("OPENAI_API_KEY")
#     if not api_key:
#         raise HTTPException(500, "OpenAI API key not configured")
#     client = OpenAI(api_key=api_key)

#     # ---------- ROUTER ----------
#     has_docs = True  # vector store may contain session/global docs

#     router_prompt = env("ROUTER_PROMPT").format(
#         query=message,
#         has_docs=has_docs
#     )

#     try:
#         route = client.chat.completions.create(
#             model=env("OPENAI_MODEL_PREPROC", "gpt-4o-mini"),
#             messages=[{"role": "system", "content": router_prompt}],
#             max_tokens=5,
#             temperature=0,
#         ).choices[0].message.content.strip().lower()
#     except Exception:
#         route = "hybrid"

#     if route not in ("rag_only", "llm_only", "hybrid"):
#         route = "hybrid"

#     # ---------- RETRIEVAL ----------
#     docs = []
#     context_text = ""

#     if route in ("rag_only", "hybrid"):
#         try:
#             docs = query_user_docs(user_email, message, top_k=env("SEARCH_TOPK_PRO", 8))
#         except Exception:
#             docs = []

#         context_text = "\n\n".join(getattr(d, "page_content", "") for d in docs)

#         # safeguard: rag_only but no context → downgrade
#         if route == "rag_only" and not context_text:
#             route = "llm_only"

#     # ---------- REASONING ----------
#     analysis = ""
#     if route == "llm_only" or (route == "hybrid" and context_text):
#         try:
#             reasoning_prompt = f"{env('REASONING_PROMPT')}\n\nQuery:\n{message}"
#             analysis = client.chat.completions.create(
#                 model=env("OPENAI_MODEL_PREPROC", "gpt-4o-mini"),
#                 messages=[{"role": "system", "content": reasoning_prompt}],
#                 max_tokens=300,
#                 temperature=0,
#             ).choices[0].message.content
#         except Exception:
#             analysis = ""

#     guard = env("PROMPT_SAFETY_GUARD")

#     # ---------- SYSTEM PROMPT ----------
#     if route == "rag_only":
#         context_mode = "docs_only"
#         source = "docs"
#         system_prompt = (
#             f"{env('PROMPT_DOCS_ONLY')}\n\n"
#             f"Document Context:\n{context_text}\n\n"
#             f"{guard}"
#         )

#     elif route == "llm_only":
#         context_mode = "external"
#         source = "gpt"
#         system_prompt = (
#             f"{env('PROMPT_LLM_ONLY')}\n\n"
#             f"Reasoning Notes:\n{analysis}\n\n"
#             f"{guard}"
#         )

#     else:
#         context_mode = "hybrid"
#         source = "docs+gpt"
#         system_prompt = (
#             f"{env('PROMPT_HYBRID')}\n\n"
#             f"Document Context:\n{context_text}\n\n"
#             f"Reasoning Notes:\n{analysis}\n\n"
#             f"{guard}"
#         )

#     # ---------- FINAL ANSWER ----------
#     try:
#         resp = client.chat.completions.create(
#             model=model,
#             messages=[
#                 {"role": "system", "content": system_prompt},
#                 {"role": "user", "content": wrap_user_content(message)},
#             ],
#             temperature=0.2,
#         )
#         ai_text = resp.choices[0].message.content.strip()
#     except Exception as e:
#         raise HTTPException(500, f"Chat generation failed: {e}")

#     # ---------- STORE ----------
#     now = datetime.utcnow()
#     db.add(ChatMessage(session_id=session_id, user_id=user.id, role="user", content=message, created_at=now))
#     db.add(ChatMessage(session_id=session_id, user_id=user.id, role="assistant", content=ai_text, created_at=now))
#     db.commit()

#     # ---------- RESPONSE ----------
#     payload = {
#         "ok": True,
#         "session_id": session_id,
#         "response": ai_text,
#         "source": source,
#         "context_mode": context_mode,
#         "route": route,
#         "model": model,
#     }
#     if created_new_session:
#         payload["title"] = _title_from_text(message)

#     return payload
