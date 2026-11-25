import asyncio
import hashlib
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine
from starlette.datastructures import UploadFile

from app import vector_store
from app.models import ChatSession, User
from app.routes import chat, upload
from app.services.conversation_attachments import attachment_document_id, completed_attachments
from app.services.grounded_answer import GroundingError
from app.storage.storage import LocalStorage


class LockingSession(Session):
    locks = {}
    locks_guard = threading.Lock()
    waiting = threading.Event()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.held_lock = None
        self.fail_commit = False
        self.fail_after_commit = False
        self.fail_link = False

    def exec(self, statement, *args, **kwargs):
        sql = str(statement)
        if "pg_advisory_xact_lock" in sql:
            key = statement.compile().params["key"]
            with self.locks_guard:
                lock = self.locks.setdefault(key, threading.Lock())
            if lock.locked():
                self.waiting.set()
            lock.acquire()
            self.held_lock = lock
            return None
        if self.fail_link and "INSERT INTO public.upload_link" in sql:
            raise RuntimeError("injected link failure")
        return super().exec(statement, *args, **kwargs)

    def _release(self):
        if self.held_lock:
            self.held_lock.release()
            self.held_lock = None

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("injected commit failure")
        super().commit()
        self._release()
        if self.fail_after_commit:
            raise RuntimeError("injected post-commit failure")

    def rollback(self):
        try:
            super().rollback()
        finally:
            self._release()

    def close(self):
        try:
            super().close()
        finally:
            self._release()


class VectorStore:
    def __init__(self):
        self.records = {}
        self.fail_partial = False
        self.upserts = 0
        self.entered = None
        self.release = None

    def upsert(self, rows):
        self.upserts += 1
        if self.entered:
            self.entered.set()
            assert self.release.wait(10)
        for row in rows:
            self.records[row.chunk_id] = row
            if self.fail_partial:
                self.fail_partial = False
                raise RuntimeError("injected partial write")

    def delete_by_doc(self, doc_id):
        self.records = {
            key: row for key, row in self.records.items() if row.doc_id != doc_id
        }

    def search(self, query_embedding, top_k, filters):
        return [
            (row, 1.0)
            for row in self.records.values()
            if all(str(row.metadata.get(k)) == str(v) for k, v in filters.items())
        ][:top_k]


@pytest.fixture
def attachment_env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'main.db'}", connect_args={"check_same_thread": False}
    )
    public_path = str(tmp_path / "public.db")

    @event.listens_for(engine, "connect")
    def attach_public(connection, _):
        connection.execute("ATTACH DATABASE ? AS public", (public_path,))

    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.exec(text("""
            CREATE TABLE public.blob (
                sha256 TEXT PRIMARY KEY, bytes INTEGER, ext TEXT, mime TEXT, storage_uri TEXT
            )
        """))
        db.exec(text("""
            CREATE TABLE public.upload_link (
                user_id INTEGER, session_id INTEGER, sha256 TEXT, doc_id TEXT,
                UNIQUE(user_id, session_id, sha256)
            )
        """))
        db.exec(text("""
            CREATE TABLE public.embedding_index (
                sha256 TEXT PRIMARY KEY, store_key TEXT, chunks INTEGER
            )
        """))
        users = [
            User(email="owner@example.test", password="hash", tier="pro"),
            User(email="other@example.test", password="hash", tier="pro"),
        ]
        for user in users:
            db.add(user)
        db.commit()
        for user in users:
            db.refresh(user)
        chats = [
            ChatSession(user_id=users[0].id, title="one"),
            ChatSession(user_id=users[0].id, title="two"),
            ChatSession(user_id=users[1].id, title="other"),
        ]
        for item in chats:
            db.add(item)
        db.commit()
        for item in chats:
            db.refresh(item)
        user_ids = [item.id for item in users]
        chat_ids = [item.id for item in chats]

    store = VectorStore()
    storage = LocalStorage(str(tmp_path / "uploads"))
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "legacy")
    monkeypatch.delenv("DISABLE_EMBED", raising=False)
    monkeypatch.setattr(upload, "_enforce_plan_upload_rates", lambda *args: None)
    monkeypatch.setattr(upload, "_enforce_plan_daily_count", lambda *args: None)
    monkeypatch.setattr(upload, "get_storage", lambda: storage)
    monkeypatch.setattr(vector_store, "PRIMARY", store)
    monkeypatch.setattr(vector_store, "SHADOWS", [])
    monkeypatch.setattr(vector_store, "_embed_texts", lambda chunks: [[0.1] for _ in chunks])
    monkeypatch.setattr(vector_store, "_embed_query", lambda query: [0.1])
    yield SimpleNamespace(
        engine=engine, users=user_ids, chats=chat_ids, store=store, storage=storage,
        path=tmp_path / "uploads",
    )
    engine.dispose()


def _upload(
    env, user_id, session_id, content, *, fail_commit=False, fail_after_commit=False,
    fail_link=False,
):
    with LockingSession(env.engine) as db:
        user = db.get(User, user_id)
        db.fail_commit = fail_commit
        db.fail_after_commit = fail_after_commit
        db.fail_link = fail_link
        return asyncio.run(upload._upload_conversation_attachment(
            request=SimpleNamespace(headers={}),
            file=UploadFile(io.BytesIO(content), filename="notes.txt"),
            session_id=session_id,
            db=db,
            user_email=user.email,
        ))


def _evidence(env, user_id, session_id):
    with LockingSession(env.engine) as db:
        return chat._conversation_attachment_evidence(
            db=db, user=db.get(User, user_id), chat=db.get(ChatSession, session_id),
            query="evidence",
        )


def test_legacy_link_is_not_complete_and_is_reindexed(attachment_env):
    env = attachment_env
    content = b"legacy attachment evidence"
    digest = hashlib.sha256(content).hexdigest()
    with LockingSession(env.engine) as db:
        db.exec(text("INSERT INTO public.upload_link VALUES (:u, :s, :h, 'legacy-id')")
                .bindparams(u=env.users[0], s=env.chats[0], h=digest))
        db.commit()
        assert completed_attachments(db, user_id=env.users[0], session_id=env.chats[0]) == {}
        check = upload.check_duplicate(
            request=SimpleNamespace(), response=SimpleNamespace(),
            session_id=env.chats[0], sha256=digest, size=len(content),
            db=db, user_email="owner@example.test",
        )
        assert check["duplicate"] is False
    assert _evidence(env, env.users[0], env.chats[0]) == ()
    result = _upload(env, env.users[0], env.chats[0], content)
    assert result["duplicate"] is False
    assert result["doc_id"] == attachment_document_id(env.users[0], env.chats[0], digest)
    assert _evidence(env, env.users[0], env.chats[0])


def test_partial_vector_write_is_hidden_and_replaced_on_retry(attachment_env):
    env = attachment_env
    content = ("attachment evidence " * 90).encode()
    env.store.fail_partial = True
    with pytest.raises(HTTPException, match="Embedding error"):
        _upload(env, env.users[0], env.chats[0], content)
    assert len(env.store.records) == 1
    assert _evidence(env, env.users[0], env.chats[0]) == ()
    assert not env.path.exists()
    result = _upload(env, env.users[0], env.chats[0], content)
    evidence = _evidence(env, env.users[0], env.chats[0])
    assert result["duplicate"] is False
    assert len(evidence) > 1
    assert len(env.store.records) == len(evidence)


def test_partial_vectors_are_rejected_even_when_another_attachment_is_complete(attachment_env):
    env = attachment_env
    _upload(env, env.users[0], env.chats[0], b"completed first attachment")
    env.store.fail_partial = True
    with pytest.raises(HTTPException, match="Embedding error"):
        _upload(env, env.users[0], env.chats[0], b"incomplete second attachment")
    evidence = _evidence(env, env.users[0], env.chats[0])
    assert len(env.store.records) == 2
    assert len(evidence) == 1
    assert "completed first attachment" in evidence[0].content


def test_commit_failure_hides_vectors_and_retry_completes(attachment_env):
    env = attachment_env
    content = b"commit failure evidence"
    with pytest.raises(RuntimeError, match="commit failure"):
        _upload(env, env.users[0], env.chats[0], content, fail_commit=True)
    assert env.store.records
    assert len(list(env.path.rglob("*.txt"))) == 1
    assert _evidence(env, env.users[0], env.chats[0]) == ()
    result = _upload(env, env.users[0], env.chats[0], content)
    assert result["duplicate"] is False
    assert _evidence(env, env.users[0], env.chats[0])
    assert _upload(env, env.users[0], env.chats[0], content)["duplicate"] is True


def test_ambiguous_successful_commit_preserves_referenced_blob(attachment_env):
    env = attachment_env
    content = b"ambiguous successful commit"
    with pytest.raises(RuntimeError, match="post-commit failure"):
        _upload(env, env.users[0], env.chats[0], content, fail_after_commit=True)
    blob = next(env.path.rglob("*.txt"))
    assert blob.read_bytes() == content
    assert _evidence(env, env.users[0], env.chats[0])
    assert _upload(env, env.users[0], env.chats[0], content)["duplicate"] is True
    assert blob.read_bytes() == content


def test_vector_backend_failure_is_not_an_empty_search(attachment_env, monkeypatch):
    env = attachment_env
    _upload(env, env.users[0], env.chats[0], b"completed attachment")

    def failed_search(*args, **kwargs):
        raise RuntimeError("private vector failure")

    monkeypatch.setattr(env.store, "search", failed_search)
    with pytest.raises(GroundingError) as failed:
        _evidence(env, env.users[0], env.chats[0])
    assert failed.value.code == "ATTACHMENT_RETRIEVAL_UNAVAILABLE"
    assert "private vector failure" not in failed.value.public_message


def test_blob_cleanup_never_deletes_shared_blob(attachment_env):
    env = attachment_env
    content = b"shared attachment evidence"
    with pytest.raises(RuntimeError, match="link failure"):
        _upload(env, env.users[0], env.chats[0], content, fail_link=True)
    assert list(env.path.rglob("*.txt")) == []
    _upload(env, env.users[0], env.chats[0], content)
    blob = next(env.path.rglob("*.txt"))
    with pytest.raises(RuntimeError, match="link failure"):
        _upload(env, env.users[1], env.chats[2], content, fail_link=True)
    assert blob.read_bytes() == content
    assert len(list(env.path.rglob("*.txt"))) == 1
    assert _evidence(env, env.users[1], env.chats[2]) == ()
    _upload(env, env.users[1], env.chats[2], content)
    _upload(env, env.users[0], env.chats[1], content)
    assert blob.read_bytes() == content
    assert len(list(env.path.rglob("*.txt"))) == 1
    assert _evidence(env, env.users[0], env.chats[0])
    assert _evidence(env, env.users[1], env.chats[2])
    assert _evidence(env, env.users[0], env.chats[1])
    assert len({item.doc_id for item in env.store.records.values()}) == 3
    with pytest.raises(GroundingError):
        _evidence(env, env.users[0], env.chats[2])


def test_concurrent_same_attachment_is_indexed_once(attachment_env):
    env = attachment_env
    env.store.entered = threading.Event()
    env.store.release = threading.Event()
    LockingSession.waiting.clear()
    content = b"concurrent attachment evidence"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_upload, env, env.users[0], env.chats[0], content)
        assert env.store.entered.wait(10)
        second = pool.submit(_upload, env, env.users[0], env.chats[0], content)
        assert LockingSession.waiting.wait(10)
        env.store.release.set()
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert sorted(result["duplicate"] for result in results) == [False, True]
    assert env.store.upserts == 1
    assert len(list(env.path.rglob("*.txt"))) == 1


def test_concurrent_users_share_only_physical_blob(attachment_env):
    env = attachment_env
    env.store.entered = threading.Event()
    env.store.release = threading.Event()
    LockingSession.waiting.clear()
    content = b"concurrent shared attachment"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_upload, env, env.users[0], env.chats[0], content)
        assert env.store.entered.wait(10)
        second = pool.submit(_upload, env, env.users[1], env.chats[2], content)
        assert LockingSession.waiting.wait(10)
        env.store.release.set()
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert all(not result["duplicate"] for result in results)
    assert results[0]["doc_id"] != results[1]["doc_id"]
    assert env.store.upserts == 2
    assert len(list(env.path.rglob("*.txt"))) == 1
    assert _evidence(env, env.users[0], env.chats[0])
    assert _evidence(env, env.users[1], env.chats[2])


def test_real_local_qdrant_scoped_upload_and_retrieval(attachment_env, monkeypatch):
    env = attachment_env
    client = vector_store.qdrant_client.QdrantClient(":memory:")
    monkeypatch.setattr(vector_store.qdrant_client, "QdrantClient", lambda **kwargs: client)
    monkeypatch.setattr(vector_store, "EMBED_DIM", 1)
    monkeypatch.setattr(vector_store, "PRIMARY", vector_store.QdrantStore())
    try:
        _upload(env, env.users[0], env.chats[0], b"real local vector evidence")
        evidence = _evidence(env, env.users[0], env.chats[0])
        assert len(evidence) == 1
        assert "real local vector evidence" in evidence[0].content
        assert _evidence(env, env.users[0], env.chats[1]) == ()
        assert _evidence(env, env.users[1], env.chats[2]) == ()
    finally:
        client.close()


def test_incomplete_embedding_batch_is_not_committed(attachment_env, monkeypatch):
    env = attachment_env
    monkeypatch.setattr(vector_store, "_embed_texts", lambda chunks: [])
    with pytest.raises(HTTPException, match="Embedding error"):
        _upload(env, env.users[0], env.chats[0], b"incomplete embeddings")
    assert not env.store.records
    assert _evidence(env, env.users[0], env.chats[0]) == ()


def test_empty_chunk_set_is_not_committed(attachment_env, monkeypatch):
    env = attachment_env
    monkeypatch.setattr(
        vector_store, "RecursiveCharacterTextSplitter",
        lambda **kwargs: SimpleNamespace(split_text=lambda _: []),
    )
    with pytest.raises(HTTPException, match="Embedding error"):
        _upload(env, env.users[0], env.chats[0], b"nonempty attachment")
    assert not env.store.records
    assert _evidence(env, env.users[0], env.chats[0]) == ()
