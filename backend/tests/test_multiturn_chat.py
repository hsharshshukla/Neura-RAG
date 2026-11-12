from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
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
from app.services.conversation_context import BoundedConversationContext, StandaloneQuery
from app.services.grounded_answer import EvidenceIndex, GroundedAnswer
from tests.test_tkp_client import _response


def database() -> tuple[object, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine, Session(engine)


def settings(workspace_id: UUID) -> TKPSettings:
    return TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        staging_workspace_id=workspace_id,
        environment="test",
        max_attempts=1,
    )


def configured_user(db: Session, workspace_id: UUID, *, email: str = "reader@example.test") -> User:
    now = datetime.now(UTC)
    user = User(email=email, password="hash", created_at=now)
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
    return user


def app_for(db: Session, user: User, bridge: TKPClient) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user.email
    return app


def test_follow_up_reretrieves_changed_evidence_and_audits_each_turn(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    user = configured_user(db, workspace_id)
    tkp_settings = settings(workspace_id)
    queries: list[str] = []
    bodies = [_response(uuid4()), _response(uuid4())]
    bodies[1] = copy.deepcopy(bodies[1])
    bodies[1]["results"][0]["projection_id"] = str(uuid4())
    bodies[1]["results"][0]["article_id"] = str(uuid4())
    bodies[1]["results"][0]["revision_id"] = str(uuid4())
    bodies[1]["results"][0]["claim_references"][0]["revision_claim_id"] = str(uuid4())
    bodies[1]["results"][0]["claim_references"][0]["candidate_claim_id"] = str(uuid4())
    bodies[1]["results"][0]["claim_references"][0]["source_fragment_ids"] = [str(uuid4())]

    async def upstream(request: httpx.Request) -> httpx.Response:
        queries.append(json.loads(request.content)["query"])
        body = bodies[len(queries) - 1]
        body["correlation_id"] = request.headers["X-Correlation-ID"]
        return httpx.Response(200, json=body)

    async def resolve_query(*, query, context, model):
        if context.messages:
            assert all(message.message_id in context.message_ids for message in context.messages)
            return StandaloneQuery(
                requires_context=True,
                context_resolved=True,
                standalone_query="Does Product X version 2 support the approved procedure?",
            )
        return StandaloneQuery(
            requires_context=False,
            context_resolved=True,
            standalone_query=query,
        )

    async def generate_answer(*, query, retrieval, model):
        citation = EvidenceIndex(retrieval).records[0].citation
        return GroundedAnswer(
            answer=f"Current approved revision is {retrieval.results[0].revision_id}. [E1]",
            confidence=0.9,
            insufficient_evidence=False,
            citations=(citation,),
        )

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: tkp_settings)
    monkeypatch.setattr(chat_routes, "resolve_conversation_query", resolve_query)
    monkeypatch.setattr(chat_routes, "generate_grounded_answer", generate_answer)
    client = TestClient(app_for(db, user, bridge))

    first = client.post("/api/v1/chat", json={"message": "How do I use Product X?"})
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]
    second = client.post(
        "/api/v1/chat",
        json={"message": "Does it support version 2?", "session_id": session_id},
    )

    assert second.status_code == 200, second.text
    assert queries == [
        "How do I use Product X?",
        "Does Product X version 2 support the approved procedure?",
    ]
    audits = db.exec(select(AnswerEvidenceAudit).order_by(AnswerEvidenceAudit.id)).all()
    assert len(audits) == 2
    assert (
        audits[0].evidence_lineage[0]["revision_id"] != audits[1].evidence_lineage[0]["revision_id"]
    )
    assert audits[1].standalone_query == queries[1]
    assert audits[1].history_message_ids == [1, 2]
    assert audits[1].citation_map[0]["revision_id"] == audits[1].evidence_lineage[0]["revision_id"]
    assert all(audit.user_id == user.id for audit in audits)
    assert all(audit.workspace_id == str(workspace_id) for audit in audits)
    assert all(audit.session_id == session_id for audit in audits)
    assert [(audit.user_message_id, audit.assistant_message_id) for audit in audits] == [
        (1, 2),
        (3, 4),
    ]
    immutable_snapshot = [
        (audit.id, audit.evidence_lineage, audit.citation_map, audit.validation_status)
        for audit in audits
    ]
    assert (
        client.patch(f"/api/v1/chat/{session_id}/title", json={"title": "Renamed"}).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/chat/{session_id}/evidence-audit", json={"validation_status": "FORGED"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/chat/{session_id}/evidence-audit").status_code == 404
    db.expire_all()
    after_endpoint_calls = db.exec(
        select(AnswerEvidenceAudit).order_by(AnswerEvidenceAudit.id)
    ).all()
    assert [
        (audit.id, audit.evidence_lineage, audit.citation_map, audit.validation_status)
        for audit in after_endpoint_calls
    ] == immutable_snapshot

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_ambiguous_follow_up_without_context_is_persisted_without_retrieval(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    user = configured_user(db, workspace_id, email="ambiguous@example.test")
    tkp_settings = settings(workspace_id)
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: tkp_settings)
    response = TestClient(app_for(db, user, bridge)).post(
        "/api/v1/chat", json={"message": "What about that?"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["insufficient_evidence"] is True
    assert "Please restate" in response.json()["response"]
    assert calls == 0
    audit = db.exec(select(AnswerEvidenceAudit)).one()
    assert audit.validation_status == "AMBIGUOUS_CONTEXT"
    assert audit.evidence_lineage == []
    assert audit.citation_map == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_workspace_bound_session_cannot_be_reused_in_other_workspace(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    engine, db = database()
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    user = configured_user(db, workspace_id, email="isolated@example.test")
    db.add(Workspace(id=str(other_workspace_id), name="other", active=True))
    chat = ChatSession(
        user_id=user.id,
        workspace_id=str(other_workspace_id),
        title="Other workspace",
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    tkp_settings = settings(workspace_id)
    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(chat_routes, "get_tkp_settings", lambda: tkp_settings)
    client = TestClient(app_for(db, user, bridge))
    response = client.post(
        "/api/v1/chat",
        json={"message": "Does it still apply?", "session_id": chat.id},
    )

    assert response.status_code == 404
    assert client.get(f"/api/v1/chat/{chat.id}").status_code == 404
    assert client.patch(f"/api/v1/chat/{chat.id}/title", json={"title": "leak"}).status_code == 404
    sessions = client.get("/api/v1/chat/sessions")
    assert sessions.status_code == 200
    assert sessions.json() == []
    assert calls == 0
    assert db.exec(select(AnswerEvidenceAudit)).all() == []

    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()


def test_history_loader_isolated_by_session_and_user(monkeypatch) -> None:
    monkeypatch.setenv("TKP_CHAT_HISTORY_MAX_MESSAGES", "10")
    engine, db = database()
    workspace_id = uuid4()
    user = configured_user(db, workspace_id, email="owner@example.test")
    other = User(email="other@example.test", password="hash")
    db.add(other)
    db.commit()
    db.refresh(other)
    first = ChatSession(user_id=user.id, workspace_id=str(workspace_id), title="first")
    second = ChatSession(user_id=user.id, workspace_id=str(workspace_id), title="second")
    db.add(first)
    db.add(second)
    db.commit()
    db.refresh(first)
    db.refresh(second)
    now = datetime.now(UTC).replace(tzinfo=None)
    db.add(
        ChatMessage(
            session_id=first.id,
            user_id=user.id,
            role="user",
            content="allowed",
            created_at=now,
            timestamp=now,
        )
    )
    db.add(
        ChatMessage(
            session_id=second.id,
            user_id=user.id,
            role="user",
            content="other session",
            created_at=now,
            timestamp=now,
        )
    )
    db.add(
        ChatMessage(
            session_id=first.id,
            user_id=other.id,
            role="assistant",
            content="other user",
            created_at=now,
            timestamp=now,
        )
    )
    db.commit()

    context = chat_routes._load_bounded_history(db, session_id=first.id, user_id=user.id)

    assert [message.content for message in context.messages] == ["allowed"]
    db.close()
    engine.dispose()


def test_evidence_audit_creation_failure_rolls_back_complete_turn(monkeypatch) -> None:
    engine, db = database()
    workspace_id = uuid4()
    user = configured_user(db, workspace_id, email="audit-failure@example.test")
    chat = ChatSession(
        user_id=user.id,
        workspace_id=str(workspace_id),
        title="Existing session",
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)

    def fail_audit(**kwargs):
        raise RuntimeError("simulated audit creation failure")

    monkeypatch.setattr(chat_routes, "build_answer_evidence_audit", fail_audit)
    grounded = GroundedAnswer(
        answer="Insufficient evidence",
        confidence=0,
        insufficient_evidence=True,
        insufficient_reason="NO_APPROVED_EVIDENCE",
    )

    with pytest.raises(RuntimeError, match="audit creation failure"):
        chat_routes._persist_tkp_turn(
            db,
            chat=chat,
            user=user,
            workspace_id=str(workspace_id),
            original_query="question",
            standalone_query="question",
            history=BoundedConversationContext(),
            retrieval_request=None,
            retrieval=None,
            grounded=grounded,
            model="test-model",
            validation_status="INSUFFICIENT_EVIDENCE",
        )

    assert db.exec(select(ChatSession)).all() == [chat]
    assert db.exec(select(ChatMessage)).all() == []
    assert db.exec(select(AnswerEvidenceAudit)).all() == []
    db.close()
    engine.dispose()


def test_commit_failure_rolls_back_new_session_messages_and_audit(monkeypatch) -> None:
    engine, db = database()
    workspace_id = uuid4()
    user = configured_user(db, workspace_id, email="commit-failure@example.test")
    grounded = GroundedAnswer(
        answer="Insufficient evidence",
        confidence=0,
        insufficient_evidence=True,
        insufficient_reason="NO_APPROVED_EVIDENCE",
    )

    def fail_commit() -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failure"):
        chat_routes._persist_tkp_turn(
            db,
            chat=None,
            user=user,
            workspace_id=str(workspace_id),
            original_query="question",
            standalone_query="question",
            history=BoundedConversationContext(),
            retrieval_request=None,
            retrieval=None,
            grounded=grounded,
            model="test-model",
            validation_status="INSUFFICIENT_EVIDENCE",
        )

    assert db.exec(select(ChatSession)).all() == []
    assert db.exec(select(ChatMessage)).all() == []
    assert db.exec(select(AnswerEvidenceAudit)).all() == []
    db.close()
    engine.dispose()
