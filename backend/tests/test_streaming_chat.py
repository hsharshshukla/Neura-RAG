from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.deps.auth import get_current_user
from app.integrations.tkp.client import TKPClient
from app.integrations.tkp.config import TKPSettings
from app.models import (
    AnswerEvidenceAudit,
    ChatMessage,
    ChatSession,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.rate_limit import limiter
from app.routes import chat as chat_routes
from app.services.grounded_answer import EvidenceIndex, GroundedAnswer, GroundingError
from tests.test_tkp_client import _response


def _database() -> tuple[object, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine, Session(engine)


def _settings(workspace_id: UUID) -> TKPSettings:
    return TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        staging_workspace_id=workspace_id,
        environment="test",
        max_attempts=1,
    )


def _configured_user(db: Session, workspace_id: UUID, email: str) -> User:
    user = User(email=email, password="hash", created_at=datetime.now(UTC))
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
    return user


def _app(db: Session, user: User, bridge: TKPClient) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email
    return app


def _events(body: str) -> list[tuple[str, dict[str, object]]]:
    parsed = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            fields[key] = value.lstrip()
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


def test_stream_releases_only_validated_chunks_then_citations_and_completion(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    monkeypatch.setenv("TKP_CHAT_STREAM_CHUNK_CHARACTERS", "64")
    engine, db = _database()
    workspace_id = uuid4()
    user = _configured_user(db, workspace_id, "stream@example.test")
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=_response(UUID(request.headers["X-Correlation-ID"])),
        )

    async def grounded(*, query, retrieval, model):
        citation = EvidenceIndex(retrieval).records[0].citation
        answer = "Validated approved procedure. " * 4 + "[E1]"
        return GroundedAnswer(
            answer=answer,
            confidence=0.91,
            insufficient_evidence=False,
            citations=(citation,),
        )

    bridge = TKPClient(_settings(workspace_id), transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: _settings(workspace_id))
    monkeypatch.setattr(chat_routes, "generate_grounded_answer", grounded)
    client = TestClient(_app(db, user, bridge))
    request_id = str(uuid4())

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "approved procedure", "request_id": request_id},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    names = [name for name, _ in events]
    assert names[:-2] and all(name == "answer" for name in names[:-2])
    assert names[-2:] == ["citations", "complete"]
    streamed = "".join(data["chunk"] for name, data in events if name == "answer")
    assert streamed == "Validated approved procedure. " * 4 + "[E1]"
    citations = events[-2][1]["citations"]
    assert citations[0]["evidence_id"] == "E1"
    assert citations[0]["title"] == "Approved fix"
    assert events[-1][1]["request_id"] == request_id
    assert events[-1][1]["replayed"] is False

    messages = db.exec(select(ChatMessage).order_by(ChatMessage.id)).all()
    audits = db.exec(select(AnswerEvidenceAudit)).all()
    assert len(messages) == 2
    assert len(audits) == 1
    assert audits[0].client_request_id == request_id
    assert audits[0].answer_confidence == pytest.approx(0.91)
    assert audits[0].citation_map == citations

    history = client.get(f"/api/v1/chat/{events[-1][1]['session_id']}")
    assert history.status_code == 200
    assert history.json()[1]["citations"] == citations

    monkeypatch.setattr(chat_routes, "plan_limit", lambda tier: 1)
    retry = client.post(
        "/api/v1/chat/stream",
        json={"message": "approved procedure", "request_id": request_id},
    )
    retry_events = _events(retry.text)
    assert retry_events[-1][1]["replayed"] is True
    assert calls == 1
    assert len(db.exec(select(ChatMessage)).all()) == 2
    assert len(db.exec(select(AnswerEvidenceAudit)).all()) == 1

    conflict = client.post(
        "/api/v1/chat/stream",
        json={"message": "different question", "request_id": request_id},
    )
    assert conflict.status_code == 409
    assert calls == 1
    assert len(db.exec(select(ChatMessage)).all()) == 2

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


@pytest.mark.parametrize("failure", ["tkp", "llm"])
def test_stream_failures_are_sanitized_and_never_persist(monkeypatch, failure: str) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = _database()
    workspace_id = uuid4()
    user = _configured_user(db, workspace_id, f"{failure}@example.test")

    async def upstream(request: httpx.Request) -> httpx.Response:
        if failure == "tkp":
            return httpx.Response(
                503,
                json={
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "private database host and credential",
                    "correlation_id": request.headers["X-Correlation-ID"],
                },
            )
        return httpx.Response(
            200,
            json=_response(UUID(request.headers["X-Correlation-ID"])),
        )

    async def grounded(*, query, retrieval, model):
        raise GroundingError(
            code="ANSWER_GENERATION_UNAVAILABLE",
            public_message="Verified answer generation is temporarily unavailable",
            status_code=503,
        )

    bridge = TKPClient(_settings(workspace_id), transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: _settings(workspace_id))
    if failure == "llm":
        monkeypatch.setattr(chat_routes, "generate_grounded_answer", grounded)
    response = TestClient(_app(db, user, bridge)).post(
        "/api/v1/chat/stream",
        json={"message": "approved procedure", "request_id": str(uuid4())},
    )

    assert response.status_code == 200
    events = _events(response.text)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["code"] in {
        "DATABASE_UNAVAILABLE",
        "ANSWER_GENERATION_UNAVAILABLE",
    }
    assert "private database" not in response.text
    assert "credential" not in response.text
    assert db.exec(select(ChatSession)).all() == []
    assert db.exec(select(ChatMessage)).all() == []
    assert db.exec(select(AnswerEvidenceAudit)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_stream_rejects_foreign_workspace_session_before_retrieval(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = _database()
    workspace_id = uuid4()
    foreign_workspace_id = uuid4()
    user = _configured_user(db, workspace_id, "isolated-stream@example.test")
    db.add(Workspace(id=str(foreign_workspace_id), name="foreign", active=True))
    foreign_chat = ChatSession(
        user_id=user.id,
        workspace_id=str(foreign_workspace_id),
        title="foreign",
    )
    db.add(foreign_chat)
    db.commit()
    db.refresh(foreign_chat)
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    bridge = TKPClient(_settings(workspace_id), transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: _settings(workspace_id))
    response = TestClient(_app(db, user, bridge)).post(
        "/api/v1/chat/stream",
        json={
            "message": "use that procedure",
            "session_id": foreign_chat.id,
            "request_id": str(uuid4()),
        },
    )

    assert response.status_code == 404
    assert calls == 0
    assert db.exec(select(AnswerEvidenceAudit)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_stream_authentication_and_billing_fail_before_retrieval(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = _database()
    workspace_id = uuid4()
    user = _configured_user(db, workspace_id, "limits-stream@example.test")
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    bridge = TKPClient(_settings(workspace_id), transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: _settings(workspace_id))
    app = _app(db, user, bridge)

    def unauthenticated() -> str:
        raise HTTPException(401, "Not authenticated")

    app.dependency_overrides[get_current_user] = unauthenticated
    client = TestClient(app)
    denied = client.post(
        "/api/v1/chat/stream",
        json={"message": "approved procedure", "request_id": str(uuid4())},
    )
    assert denied.status_code == 401

    app.dependency_overrides[get_current_user] = lambda: user.email
    monkeypatch.setattr(chat_routes, "plan_limit", lambda tier: 1)
    monkeypatch.setattr(chat_routes, "_today_user_chat_count", lambda db, user_id: 1)
    limited = client.post(
        "/api/v1/chat/stream",
        json={"message": "approved procedure", "request_id": str(uuid4())},
    )
    assert limited.status_code == 429
    assert calls == 0
    assert db.exec(select(ChatSession)).all() == []
    assert db.exec(select(ChatMessage)).all() == []
    assert db.exec(select(AnswerEvidenceAudit)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_stream_preparation_emits_nothing_and_propagates() -> None:
    started = asyncio.Event()

    async def prepare() -> dict[str, object]:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    stream = chat_routes._stream_tkp_events(
        request=ConnectedRequest(),
        prepare=prepare,
        request_id=str(uuid4()),
    )
    task = asyncio.create_task(anext(stream))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
