"""Focused conversation-attachment tests; all external dependencies are mocked."""

from __future__ import annotations

import io
import json
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from starlette.datastructures import Headers, UploadFile

from app.db import get_session
from app.deps.auth import get_current_user
from app.models import ChatSession, User
from app.routes import chat as chat_routes
from app.routes import upload as upload_routes
from app.services.grounded_answer import (
    AttachmentEvidence,
    GroundedAnswerService,
)
from app.services.conversation_attachments import attachment_document_id
from app.vector_scope import build_retrieval_filters
from tests.test_grounded_answer import FakeLLM, retrieval


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value

    def one(self):
        return self.value

    def mappings(self):
        return self


class _UploadDB:
    """Small SQL fake for upload routing; no live database or blob store is used."""

    def __init__(
        self,
        user: User,
        *,
        linked_doc_id: str | None = None,
        existing_blob: bool = False,
        blob_size: int = 10,
    ):
        self.user = user
        self.linked_doc_id = linked_doc_id
        self.existing_blob = existing_blob
        self.blob_size = blob_size
        self.links = {}
        self.blob_lookups = 0
        self.link_lookups = 0
        self.commits = 0

    def exec(self, statement):
        sql = str(statement)
        params = statement.compile().params
        if "FROM \"user\"" in sql:
            return _Result(self.user)
        if "COUNT(1) FROM public.upload_link" in sql:
            return _Result((0,))
        if "SELECT doc_id FROM public.upload_link" in sql:
            self.link_lookups += 1
            doc_id = self.links.get((params["u"], params["s"], params["h"]))
            doc_id = doc_id or self.linked_doc_id
            return _Result((doc_id,) if doc_id else None)
        if "SELECT 1 FROM public.upload_link" in sql:
            self.link_lookups += 1
            doc_id = self.links.get((params["u"], params["s"], params["h"]))
            doc_id = doc_id or self.linked_doc_id
            return _Result((1,) if doc_id == params["d"] else None)
        if "FROM public.blob" in sql:
            self.blob_lookups += 1
            return _Result(
                {"sha256": "existing", "bytes": self.blob_size, "storage_uri": "mock://existing"}
                if self.existing_blob
                else None
            )
        if "INSERT INTO public.blob" in sql:
            self.existing_blob = True
            self.blob_size = params["b"]
            return _Result(None)
        if "INSERT INTO public.upload_link" in sql:
            self.links[(params["u"], params["s"], params["h"])] = params["d"]
            return _Result(None)
        return _Result(None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _upload_app(db: _UploadDB, email: str) -> FastAPI:
    app = FastAPI()
    app.state.limiter = upload_routes.limiter
    app.include_router(upload_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: email
    return app


async def _call_upload(**kwargs):
    """Call the FastAPI endpoint beneath SlowAPI's request-type wrapper."""

    return await upload_routes.upload_file.__wrapped__(**kwargs)


def test_tkp_owned_session_check_and_upload_are_conversation_endpoints(
    monkeypatch,
) -> None:
    """Mocked HTTP test: blob, parser, embedding, storage, and auth are fakes."""

    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    user = User(id=7, email="owner@example.test", password="hash", tier="pro")
    chat = ChatSession(id=19, user_id=7, workspace_id=str(uuid4()), title="owned")
    db = _UploadDB(user)
    indexed = []
    saved = []
    monkeypatch.setattr(
        upload_routes,
        "_require_attachment_session",
        lambda db, user, session_id: chat
        if session_id == chat.id
        else (_ for _ in ()).throw(HTTPException(404, "Chat not found")),
    )
    monkeypatch.setattr(upload_routes, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload_routes, "_enforce_plan_daily_count", lambda *args: None)
    monkeypatch.setattr(
        upload_routes,
        "parse_and_clean_bytes",
        lambda *args: {"text": "private attachment evidence"},
    )
    monkeypatch.setattr(
        upload_routes,
        "embed_and_store",
        lambda **kwargs: indexed.append(kwargs),
    )
    monkeypatch.setattr(
        upload_routes,
        "get_storage",
        lambda: SimpleNamespace(
            save_stream=lambda **kwargs: saved.append(kwargs) or ("doc", "mock://blob")
        ),
    )
    client = TestClient(_upload_app(db, user.email))

    check = client.get(
        "/api/v1/upload/check",
        params={"session_id": chat.id, "sha256": "a" * 64, "size": 4},
    )
    uploaded = client.post(
        "/api/v1/upload",
        data={"session_id": str(chat.id)},
        files={"file": ("../safe.txt", b"same bytes", "text/plain")},
    )

    assert check.status_code == 200, check.text
    assert check.json()["duplicate"] is False
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["duplicate"] is False
    assert uploaded.json()["session_id"] == chat.id
    assert saved[0]["filename"] == "safe.txt"
    metadata = indexed[0]["metadata"]
    assert metadata["attachment_kind"] == "conversation_attachment"
    assert metadata["user_id"] == str(user.id)
    assert metadata["user_email"] == user.email
    assert metadata["session_id"] == str(chat.id)
    assert metadata["filename"] == "safe.txt"
    assert metadata["doc_id"] != metadata["sha256"]
    completed = client.get(
        "/api/v1/upload/check",
        params={"session_id": chat.id, "sha256": metadata["sha256"], "size": 10},
    )
    assert completed.status_code == 200
    assert completed.json()["duplicate"] is True


def test_upload_auth_and_session_denials_precede_blob_disclosure(monkeypatch) -> None:
    """Mocked HTTP test: absent and foreign sessions share the same response."""

    user = User(id=8, email="reader@example.test", password="hash")
    db = _UploadDB(user)
    app = _upload_app(db, user.email)

    def unauthenticated():
        raise HTTPException(401, "Not authenticated")

    app.dependency_overrides[get_current_user] = unauthenticated
    client = TestClient(app)
    assert (
        client.get(
            "/api/v1/upload/check",
            params={"session_id": 1, "sha256": "b" * 64, "size": 1},
        ).status_code
        == 401
    )

    app.dependency_overrides[get_current_user] = lambda: user.email
    monkeypatch.setattr(
        upload_routes,
        "_require_attachment_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPException(404, "Chat not found")
        ),
    )
    missing = client.get(
        "/api/v1/upload/check",
        params={"session_id": 404, "sha256": "b" * 64, "size": 1},
    )
    foreign = client.get(
        "/api/v1/upload/check",
        params={"session_id": 405, "sha256": "b" * 64, "size": 1},
    )
    assert (missing.status_code, missing.json()) == (foreign.status_code, foreign.json())
    assert missing.status_code == 404
    assert db.blob_lookups == 0
    assert db.link_lookups == 0


def test_global_blob_existence_is_not_disclosed_as_a_conversation_duplicate(
    monkeypatch,
) -> None:
    """Mocked HTTP check never queries or reveals cross-tenant physical blobs."""

    user = User(id=18, email="tenant-b@example.test", password="hash")
    chat = ChatSession(id=51, user_id=user.id, title="tenant-b")
    db = _UploadDB(user, existing_blob=True)
    monkeypatch.setattr(
        upload_routes,
        "_require_attachment_session",
        lambda *args, **kwargs: chat,
    )
    client = TestClient(_upload_app(db, user.email))

    response = client.get(
        "/api/v1/upload/check",
        params={"session_id": chat.id, "sha256": "c" * 64, "size": 12},
    )

    assert response.status_code == 200
    assert response.json()["exists"] is False
    assert response.json()["duplicate"] is False
    assert response.json()["linked"] is False
    assert db.blob_lookups == 0


@pytest.mark.asyncio
async def test_upload_file_is_closed_when_authorization_fails(monkeypatch) -> None:
    """Mocked resource-lifecycle test; parsing and storage must never start."""

    upload = UploadFile(
        io.BytesIO(b"secret"),
        filename="secret.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    closed = 0
    original_close = upload.close

    async def tracked_close():
        nonlocal closed
        closed += 1
        await original_close()

    upload.close = tracked_close
    monkeypatch.setattr(
        upload_routes,
        "_upload_conversation_attachment",
        lambda **kwargs: (_ for _ in ()).throw(HTTPException(404, "Chat not found")),
    )
    with pytest.raises(HTTPException) as denied:
        await _call_upload(
            request=SimpleNamespace(),
            response=SimpleNamespace(),
            file=upload,
            session_id=1,
            db=SimpleNamespace(),
            user_email="owner@example.test",
        )
    assert denied.value.status_code == 404
    assert closed == 1


@pytest.mark.asyncio
async def test_global_blob_dedup_does_not_suppress_cross_session_indexing(
    monkeypatch,
) -> None:
    """Mocked dedup test: the same bytes still get distinct scoped document IDs."""

    user = User(id=9, email="owner@example.test", password="hash", tier="pro")
    db = _UploadDB(user, existing_blob=True)
    indexed = []
    monkeypatch.setattr(
        upload_routes,
        "_require_attachment_session",
        lambda db, user, session_id: ChatSession(
            id=session_id, user_id=user.id, title="owned"
        ),
    )
    monkeypatch.setattr(upload_routes, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload_routes, "_enforce_plan_daily_count", lambda *args: None)
    monkeypatch.setattr(
        upload_routes,
        "parse_and_clean_bytes",
        lambda *args: {"text": "same parsed bytes"},
    )
    monkeypatch.setattr(
        upload_routes,
        "embed_and_store",
        lambda **kwargs: indexed.append(kwargs),
    )
    monkeypatch.setattr(
        upload_routes,
        "get_storage",
        lambda: pytest.fail("existing global blob must be reused"),
    )

    results = []
    for session_id in (21, 22):
        upload = UploadFile(io.BytesIO(b"same bytes"), filename="same.txt")
        result = await _call_upload(
            request=SimpleNamespace(headers={}),
            response=SimpleNamespace(),
            file=upload,
            session_id=session_id,
            db=db,
            user_email=user.email,
        )
        results.append(result)

    assert len(indexed) == 2
    assert [call["metadata"]["session_id"] for call in indexed] == ["21", "22"]
    assert results[0]["doc_id"] != results[1]["doc_id"]
    assert all(result["duplicate"] is False for result in results)


@pytest.mark.asyncio
async def test_same_conversation_duplicate_skips_reindex_only_after_success(
    monkeypatch,
) -> None:
    """Mocked logical duplicate test: a completed link is the only skip marker."""

    user = User(id=29, email="owner@example.test", password="hash", tier="pro")
    chat = ChatSession(id=61, user_id=user.id, title="owned")
    db = _UploadDB(user, existing_blob=True)
    indexed = []
    monkeypatch.setattr(
        upload_routes, "_require_attachment_session", lambda *args, **kwargs: chat
    )
    monkeypatch.setattr(upload_routes, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload_routes, "_enforce_plan_daily_count", lambda *args: None)
    monkeypatch.setattr(
        upload_routes,
        "parse_and_clean_bytes",
        lambda *args: {"text": "same conversation evidence"},
    )
    monkeypatch.setattr(
        upload_routes,
        "embed_and_store",
        lambda **kwargs: indexed.append(kwargs),
    )

    first = await _call_upload(
        request=SimpleNamespace(headers={}),
        response=SimpleNamespace(),
        file=UploadFile(io.BytesIO(b"same bytes"), filename="same.txt"),
        session_id=chat.id,
        db=db,
        user_email=user.email,
    )
    second = await _call_upload(
        request=SimpleNamespace(headers={}),
        response=SimpleNamespace(),
        file=UploadFile(io.BytesIO(b"same bytes"), filename="same.txt"),
        session_id=chat.id,
        db=db,
        user_email=user.email,
    )

    assert first["duplicate"] is False
    assert second == {
        "ok": True,
        "duplicate": True,
        "session_id": chat.id,
        "doc_id": first["doc_id"],
        "chars_indexed": 0,
    }
    assert len(indexed) == 1


@pytest.mark.asyncio
async def test_failed_indexing_leaves_attachment_retryable(monkeypatch) -> None:
    """Mocked retry test: no logical link is written until vector indexing succeeds."""

    user = User(id=30, email="retry@example.test", password="hash", tier="pro")
    chat = ChatSession(id=62, user_id=user.id, title="retry")
    db = _UploadDB(user, existing_blob=True, blob_size=len(b"retry bytes"))
    attempts = 0

    def index(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("mock vector outage")

    monkeypatch.setattr(
        upload_routes, "_require_attachment_session", lambda *args, **kwargs: chat
    )
    monkeypatch.setattr(upload_routes, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload_routes, "_enforce_plan_daily_count", lambda *args: None)
    monkeypatch.setattr(
        upload_routes,
        "parse_and_clean_bytes",
        lambda *args: {"text": "retryable evidence"},
    )
    monkeypatch.setattr(upload_routes, "embed_and_store", index)

    with pytest.raises(HTTPException) as failed:
        await _call_upload(
            request=SimpleNamespace(headers={}),
            response=SimpleNamespace(),
            file=UploadFile(io.BytesIO(b"retry bytes"), filename="retry.txt"),
            session_id=chat.id,
            db=db,
            user_email=user.email,
        )
    assert failed.value.status_code == 500
    assert db.links == {}

    retried = await _call_upload(
        request=SimpleNamespace(headers={}),
        response=SimpleNamespace(),
        file=UploadFile(io.BytesIO(b"retry bytes"), filename="retry.txt"),
        session_id=chat.id,
        db=db,
        user_email=user.email,
    )
    assert retried["duplicate"] is False
    assert retried["chars_indexed"] == len("retryable evidence")
    assert attempts == 2


@pytest.mark.asyncio
async def test_same_bytes_are_independently_indexed_for_different_users(
    monkeypatch,
) -> None:
    """Mocked tenant test: physical reuse never suppresses per-owner indexing."""

    indexed = []
    monkeypatch.setattr(
        upload_routes,
        "_require_attachment_session",
        lambda db, *, user, session_id: ChatSession(
            id=session_id,
            user_id=user.id,
            title="authorized",
        ),
    )
    monkeypatch.setattr(upload_routes, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload_routes, "_enforce_plan_daily_count", lambda *args: None)
    monkeypatch.setattr(
        upload_routes,
        "parse_and_clean_bytes",
        lambda *args: {"text": "shared bytes, private attachment"},
    )
    monkeypatch.setattr(
        upload_routes,
        "embed_and_store",
        lambda **kwargs: indexed.append(kwargs),
    )
    monkeypatch.setattr(
        upload_routes,
        "get_storage",
        lambda: pytest.fail("the existing physical blob should be reused"),
    )

    results = []
    for user_id, session_id in ((41, 71), (42, 72)):
        user = User(
            id=user_id,
            email=f"owner-{user_id}@example.test",
            password="hash",
            tier="pro",
        )
        results.append(
            await _call_upload(
                request=SimpleNamespace(headers={}),
                response=SimpleNamespace(),
                file=UploadFile(io.BytesIO(b"identical bytes"), filename="shared.txt"),
                session_id=session_id,
                db=_UploadDB(user, existing_blob=True, blob_size=len(b"identical bytes")),
                user_email=user.email,
            )
        )

    assert [call["metadata"]["user_id"] for call in indexed] == ["41", "42"]
    assert [call["metadata"]["session_id"] for call in indexed] == ["71", "72"]
    assert results[0]["doc_id"] != results[1]["doc_id"]
    assert all(result["duplicate"] is False for result in results)


@pytest.mark.asyncio
async def test_supported_type_size_limit_and_same_session_duplicate_are_preserved(
    monkeypatch,
) -> None:
    """Mocked policy test covering type, plan-size, and linked duplicate behavior."""

    user = User(id=10, email="limits@example.test", password="hash", tier="free")
    chat = ChatSession(id=31, user_id=user.id, title="owned")
    monkeypatch.setattr(
        upload_routes,
        "_require_attachment_session",
        lambda *args, **kwargs: chat,
    )
    monkeypatch.setattr(upload_routes, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload_routes, "_enforce_plan_daily_count", lambda *args: None)

    unsupported = UploadFile(io.BytesIO(b"x"), filename="malware.exe")
    with pytest.raises(HTTPException) as bad_type:
        await _call_upload(
            request=SimpleNamespace(headers={}),
            response=SimpleNamespace(),
            file=unsupported,
            session_id=chat.id,
            db=_UploadDB(user),
            user_email=user.email,
        )
    assert bad_type.value.status_code == 415
    assert unsupported.file.closed

    oversized = UploadFile(io.BytesIO(b"x"), filename="notes.txt")
    with pytest.raises(HTTPException) as too_large:
        await _call_upload(
            request=SimpleNamespace(headers={"content-length": str(6 * 1024 * 1024)}),
            response=SimpleNamespace(),
            file=oversized,
            session_id=chat.id,
            db=_UploadDB(user),
            user_email=user.email,
        )
    assert too_large.value.status_code == 413
    assert oversized.file.closed

    linked = UploadFile(io.BytesIO(b"already linked"), filename="notes.txt")
    existing_doc_id = attachment_document_id(
        user.id, chat.id, hashlib.sha256(b"already linked").hexdigest()
    )
    result = await _call_upload(
        request=SimpleNamespace(headers={}),
        response=SimpleNamespace(),
        file=linked,
        session_id=chat.id,
        db=_UploadDB(user, linked_doc_id=existing_doc_id),
        user_email=user.email,
    )
    assert result == {
        "ok": True,
        "duplicate": True,
        "session_id": chat.id,
        "doc_id": existing_doc_id,
        "chars_indexed": 0,
    }
    assert linked.file.closed


def test_attachment_retrieval_is_user_and_session_scoped_even_for_pro(monkeypatch) -> None:
    """Mocked vector search returns mixed data; the boundary rejects foreign hits."""

    user = User(id=3, email="pro@example.test", password="hash", tier="pro")
    chat = ChatSession(id=11, user_id=3, title="active")
    captured = {}
    allowed = {
        "attachment_kind": "conversation_attachment",
        "user_id": "3",
        "session_id": "11",
        "filename": "allowed.txt",
        "user_email": user.email,
        "sha256": "a" * 64,
        "doc_id": attachment_document_id(user.id, chat.id, "a" * 64),
        "chunk_id": "chunk-allowed",
    }

    def fake_query(user_email, question, **kwargs):
        captured.update(user_email=user_email, question=question, **kwargs)
        return [
            Document(page_content="allowed", metadata=allowed),
            Document(
                page_content="other session",
                metadata={**allowed, "session_id": "12", "chunk_id": "foreign-session"},
            ),
            Document(
                page_content="other user",
                metadata={**allowed, "user_id": "4", "chunk_id": "foreign-user"},
            ),
        ]

    monkeypatch.setattr(chat_routes, "query_user_docs", fake_query)
    monkeypatch.setattr(
        chat_routes, "completed_attachments", lambda *args, **kwargs: {"a" * 64: allowed["doc_id"]}
    )
    evidence = chat_routes._conversation_attachment_evidence(
        db=SimpleNamespace(), user=user, chat=chat, query="question"
    )

    assert captured["filter_by_user"] is True
    assert captured["extra_filters"] == {
        "attachment_kind": "conversation_attachment",
        "user_id": "3",
        "session_id": "11",
    }
    assert [(item.document_id, item.chunk_id) for item in evidence] == [
        (allowed["doc_id"], "chunk-allowed")
    ]
    assert build_retrieval_filters("pro", "pro@example.test", "11", "3") == {
        "user_email": "pro@example.test",
        "user_id": "3",
    }


@pytest.mark.asyncio
async def test_grounding_combines_tkp_and_attachment_evidence_with_usable_citations() -> None:
    """Mocked LLM test: no live model or TKP service is called."""

    llm = FakeLLM(
        json.dumps(
            {
                "insufficient_evidence": False,
                "claims": [
                    {
                        "claim_id": "C1",
                        "text": "Use the approved fix and the attached local detail.",
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
    tkp = retrieval()
    attachment = AttachmentEvidence(
        content="local detail",
        filename="notes.txt",
        document_id="doc-1",
        chunk_id="chunk-1",
        user_id="3",
        session_id="11",
    )

    answer = await GroundedAnswerService(llm).generate(
        query="question", retrieval=tkp, attachments=(attachment,)
    )

    assert [item.evidence_id for item in answer.citations] == ["E1", "E2"]
    tkp_citation = answer.citations[0].model_dump(mode="json")
    attachment_citation = answer.citations[1].model_dump(mode="json")
    assert tkp_citation["projection_id"] == str(tkp.results[0].projection_id)
    assert tkp_citation["source_fragment_ids"]
    assert attachment_citation == {
        "evidence_id": "E2",
        "title": "notes.txt",
        "relevant_section": "Conversation attachment",
        "heading_path": [],
        "sources": [],
        "attachment_kind": "conversation_attachment",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
    }


@pytest.mark.asyncio
async def test_stream_emits_combined_citations() -> None:
    """Mocked SSE test: prepared validated output contains both evidence tiers."""

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    citations = [
        {"evidence_id": "E1", "title": "Approved TKP evidence"},
        {
            "evidence_id": "E2",
            "title": "notes.txt",
            "attachment_kind": "conversation_attachment",
        },
    ]

    async def prepare():
        return {
            "answer": "combined [E1, E2]",
            "citations": citations,
            "session_id": 11,
            "confidence": 0.9,
        }

    events = [
        event
        async for event in chat_routes._stream_tkp_events(
            request=ConnectedRequest(), prepare=prepare, request_id=str(uuid4())
        )
    ]
    citation_event = next(event for event in events if "event: citations" in event)
    payload = json.loads(citation_event.split("data: ", 1)[1])
    assert payload["citations"] == citations
