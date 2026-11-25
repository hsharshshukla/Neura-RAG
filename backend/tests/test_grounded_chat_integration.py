from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from pydantic import SecretStr
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.deps.auth import get_current_user
from app.integrations.tkp.client import TKPClient
from app.integrations.tkp.config import TKPSettings
from app.models import ChatMessage, ChatSession, User, Workspace, WorkspaceMembership
from app.rate_limit import limiter
from app.routes import chat as chat_routes
from app.services.grounded_answer import GroundedAnswerService
from app.services.conversation_attachments import attachment_document_id
from tests.test_tkp_client import _response


class FakeLLM:
    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)

    async def complete(self, messages: Sequence[dict[str, str]]) -> str:
        return self.outputs.pop(0)


def database() -> tuple[object, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    db = Session(engine)
    db.exec(text("ATTACH DATABASE ':memory:' AS public"))
    db.exec(text("CREATE TABLE public.upload_link (user_id INTEGER, session_id INTEGER, sha256 TEXT, doc_id TEXT)"))
    return engine, db


def settings(workspace_id: UUID) -> TKPSettings:
    return TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        staging_workspace_id=workspace_id,
        environment="test",
        max_attempts=1,
    )


def test_tkp_chat_retrieves_generates_validates_and_persists(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    now = datetime.now(UTC)
    user = User(email="reader@example.test", password="hash", created_at=now)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Workspace(id=str(workspace_id), name="staging", active=True, created_at=now))
    db.add(
        WorkspaceMembership(
            workspace_id=str(workspace_id),
            user_id=user.id,
            role="reader",
            created_at=now,
        )
    )
    db.commit()
    chat = ChatSession(
        user_id=user.id,
        workspace_id=str(workspace_id),
        title="attachment conversation",
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    sha256 = "a" * 64
    doc_id = attachment_document_id(user.id, chat.id, sha256)
    db.exec(text("INSERT INTO public.upload_link VALUES (:u, :s, :h, :d)").bindparams(
        u=user.id, s=chat.id, h=sha256, d=doc_id
    ))
    db.commit()
    tkp_settings = settings(workspace_id)
    captured: dict[str, object] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured["request"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_response(UUID(request.headers["X-Correlation-ID"])),
        )

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    llm = FakeLLM(
        json.dumps(
            {
                "insufficient_evidence": False,
                "claims": [
                    {
                        "claim_id": "C1",
                        "text": "Use the approved procedure and the attached local detail.",
                        "evidence_ids": ["E1", "E2"],
                    }
                ],
                "confidence": 0.9,
            }
        ),
        json.dumps(
            {
                "results": [{"claim_id": "C1", "supported": True}],
                "contradictory_evidence": False,
            }
        ),
    )

    async def generate_grounded_answer(*, query, retrieval, model, attachments=()):
        assert [item.content for item in attachments] == ["attached local detail"]
        return await GroundedAnswerService(llm).generate(
            query=query, retrieval=retrieval, attachments=attachments
        )

    def attachment_query(user_email, question, **kwargs):
        assert kwargs["extra_filters"] == {
            "attachment_kind": "conversation_attachment",
            "user_id": str(user.id),
            "session_id": str(chat.id),
        }
        return [
            Document(
                page_content="attached local detail",
                metadata={
                    **kwargs["extra_filters"],
                    "user_email": user.email,
                    "sha256": sha256,
                    "filename": "notes.txt",
                    "doc_id": doc_id,
                    "chunk_id": "attachment-chunk",
                },
            ),
            Document(
                page_content="incomplete private detail",
                metadata={
                    **kwargs["extra_filters"],
                    "user_email": user.email,
                    "sha256": "e" * 64,
                    "filename": "incomplete.txt",
                    "doc_id": attachment_document_id(user.id, chat.id, "e" * 64),
                    "chunk_id": "incomplete-chunk",
                },
            ),
        ]

    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: tkp_settings)
    monkeypatch.setattr(chat_routes, "generate_grounded_answer", generate_grounded_answer)
    monkeypatch.setattr(chat_routes, "query_user_docs", attachment_query)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email

    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": "approved fix", "session_id": chat.id},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["response"] == (
        "Use the approved procedure and the attached local detail. [E1, E2]"
    )
    assert payload["source"] == "tkp"
    assert payload["insufficient_evidence"] is False
    assert payload["citations"][0]["projection_id"]
    assert payload["citations"][0]["source_fragment_ids"]
    assert payload["citations"][1]["attachment_kind"] == "conversation_attachment"
    assert payload["citations"][1]["title"] == "notes.txt"
    assert "workspace_id" not in captured["request"]
    assert "attached local detail" not in json.dumps(captured["request"])
    assert db.exec(select(ChatSession)).all()
    messages = db.exec(select(ChatMessage).order_by(ChatMessage.id)).all()
    assert [(message.role, message.content) for message in messages] == [
        ("user", "approved fix"),
        (
            "assistant",
            "Use the approved procedure and the attached local detail. [E1, E2]",
        ),
    ]

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_tkp_chat_fails_before_retrieval_without_workspace_membership(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    user = User(email="outsider@example.test", password="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    tkp_settings = settings(workspace_id)
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: tkp_settings)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email

    response = TestClient(app).post("/api/v1/chat", json={"message": "private fix"})

    assert response.status_code == 403
    assert calls == 0
    assert db.exec(select(ChatSession)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_attachment_retrieval_failure_is_explicit_and_never_persists(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    user = User(email="attachment-failure@example.test", password="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Workspace(id=str(workspace_id), name="staging", active=True))
    db.add(WorkspaceMembership(workspace_id=str(workspace_id), user_id=user.id, role="reader"))
    chat = ChatSession(user_id=user.id, workspace_id=str(workspace_id), title="owned")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    digest = "c" * 64
    db.exec(text("INSERT INTO public.upload_link VALUES (:u, :s, :h, :d)").bindparams(
        u=user.id, s=chat.id, h=digest, d=attachment_document_id(user.id, chat.id, digest)
    ))
    db.commit()

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(UUID(request.headers["X-Correlation-ID"])))

    def failed_query(*args, **kwargs):
        raise RuntimeError("private vector credential")

    bridge = TKPClient(settings(workspace_id), transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: settings(workspace_id))
    monkeypatch.setattr(chat_routes, "query_user_docs", failed_query)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email
    response = TestClient(app).post(
        "/api/v1/chat", json={"message": "attachment", "session_id": chat.id}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "ATTACHMENT_RETRIEVAL_UNAVAILABLE"
    assert "private vector credential" not in response.text
    assert db.exec(select(ChatMessage)).all() == []
    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_tkp_failure_does_not_persist_or_fall_back_to_legacy_rag(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    user = User(email="reader-failure@example.test", password="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Workspace(id=str(workspace_id), name="staging", active=True))
    db.add(
        WorkspaceMembership(
            workspace_id=str(workspace_id),
            user_id=user.id,
            role="reader",
        )
    )
    db.commit()
    tkp_settings = settings(workspace_id)

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "code": "DATABASE_UNAVAILABLE",
                "message": "sensitive upstream detail",
                "correlation_id": request.headers["X-Correlation-ID"],
            },
        )

    async def forbidden_generation(*args, **kwargs):
        pytest.fail("answer generation must not run after TKP failure")

    def forbidden_legacy(*args, **kwargs):
        pytest.fail("legacy organizational RAG must not run in TKP mode")

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: tkp_settings)
    monkeypatch.setattr(chat_routes, "generate_grounded_answer", forbidden_generation)
    monkeypatch.setattr(chat_routes, "query_user_docs", forbidden_legacy)
    monkeypatch.setattr(chat_routes, "OpenAI", forbidden_legacy)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email

    response = TestClient(app).post("/api/v1/chat", json={"message": "approved fix"})

    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "sensitive upstream detail" not in response.text
    assert db.exec(select(ChatSession)).all() == []
    assert db.exec(select(ChatMessage)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_billing_limit_blocks_tkp_retrieval_and_session_creation(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    user = User(email="limited@example.test", password="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    tkp_settings = settings(uuid4())
    upstream_calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(500)

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "plan_limit", lambda tier: 1)
    monkeypatch.setattr(chat_routes, "_today_user_chat_count", lambda db, user_id: 1)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email

    response = TestClient(app).post("/api/v1/chat", json={"message": "approved fix"})

    assert response.status_code == 429
    assert upstream_calls == 0
    assert db.exec(select(ChatSession)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()
