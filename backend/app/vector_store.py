# app/vector_store.py
"""
Vector store abstraction with Chroma (default), pgvector, and Qdrant support.
Public API kept compatible:
  - embed_and_store(user_email, text, metadata)
  - query_user_docs(user_email, question, top_k=4, filter_by_user=True, extra_filters=None)
  - get_vector_stats()
  - search_vectors(question, top_k=10, filters=None)   # back-compat shim for retrieval.py

Env knobs (examples):
  VECTOR_PRIMARY=chroma|pgvector|qdrant
  VECTOR_SHADOWS=qdrant
  VECTOR_SHADOW_READ=true
  VECTOR_NAMESPACE=prod
  EMBEDDING_MODEL=text-embedding-3-large
  EMBED_DIM=3072

Qdrant Cloud:
  QDRANT_URL=https://<cluster>.<region>.cloud.qdrant.io
  QDRANT_API_KEY=xxxxxxxx
Self-hosted Qdrant:
  QDRANT_HOST=localhost
  QDRANT_PORT=6333

pgvector:
  PGVECTOR_TABLE=embedding_index  (requires: CREATE EXTENSION IF NOT EXISTS vector;)
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any, Iterable, Tuple, Protocol
from dataclasses import dataclass
import os, json, math, hashlib, logging, time, re
from datetime import datetime
from contextlib import contextmanager
from dotenv import load_dotenv


from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma


# SQLModel Session (we'll obtain engine/session via app.db.get_session dynamically)
from sqlmodel import Session

load_dotenv()
log = logging.getLogger("vector-store")

# ----------------------- Config -----------------------
CHROMA_DIR = os.getenv(
    "VECTOR_STORE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vector_store"))
)

# Model env: support both names
EMBED_MODEL = os.getenv("EMBEDDING_MODEL") or os.getenv("EMBED_MODEL", "text-embedding-3-large")
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))  # keep in sync with your embedding model

# Backend selection
VECTOR_PRIMARY = (os.getenv("VECTOR_PRIMARY") or os.getenv("VECTOR_BACKEND") or "chroma").strip().lower()
VECTOR_SHADOWS = [s.strip().lower() for s in (os.getenv("VECTOR_SHADOWS", "").split(",") if os.getenv("VECTOR_SHADOWS") else [])]
VECTOR_SHADOW_READ = os.getenv("VECTOR_SHADOW_READ", "false").lower() == "true"
VECTOR_NAMESPACE = os.getenv("VECTOR_NAMESPACE", "prod")

# pgvector table
PGVECTOR_TABLE = os.getenv("PGVECTOR_TABLE", "embedding_index")

# Qdrant (optional)
try:
    import qdrant_client
    from qdrant_client.http import models as qm
    from qdrant_client.http.exceptions import UnexpectedResponse
except Exception:
    qdrant_client = None
    qm = None
    UnexpectedResponse = Exception  # fallback

# ----------------------- Interface -----------------------
@dataclass(frozen=True)
class VectorRecord:
    doc_id: str
    chunk_id: str
    text: str
    embedding: List[float]
    metadata: Dict[str, Any]

class VectorStore(Protocol):
    def upsert(self, rows: Iterable[VectorRecord]) -> None: ...
    def delete_by_doc(self, doc_id: str) -> None: ...
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[VectorRecord, float]]: ...
    def flush(self) -> None: ...
    def stats(self) -> Dict[str, str]: ...

# ----------------------- DB Session Helper -----------------------
@contextmanager
def _session_scope():
    """
    Works with your existing app.db.get_session() FastAPI dependency (yielding a Session).
    Falls back to app.db.engine if present. Raises a clear error otherwise.
    """
    get_sess = None
    engine = None
    try:
        from app.db import get_session as _gs  # typical: yields Session
        get_sess = _gs
    except Exception:
        pass
    if get_sess:
        gen = get_sess()
        s = next(gen)  # obtain the Session yielded by dependency
        try:
            yield s
        finally:
            try:
                next(gen)  # run generator finalizer/close
            except StopIteration:
                pass
        return
    # fallback path
    try:
        from app.db import engine as _engine
        engine = _engine
    except Exception:
        pass
    if engine is None:
        raise RuntimeError("Neither app.db.get_session nor app.db.engine is available.")
    with Session(engine) as s:
        yield s

# ----------------------- Utilities -----------------------
def _get_embeddings() -> OpenAIEmbeddings:
    # Lazily create to avoid import-time failures if key is missing
    return OpenAIEmbeddings(model=EMBED_MODEL)

def _normalize_metadata(md: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    md = (md or {}).copy()
    if "session_id" in md and md["session_id"] is not None:
        # We treat session_id as string for uniformity across backends and indexing as KEYWORD in Qdrant
        md["session_id"] = str(md["session_id"])
    md["__ns"] = VECTOR_NAMESPACE
    return md

def _build_where_from_kv(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Used only by Chroma; other backends use flat filters directly
    clauses: List[Dict[str, Any]] = [{k: v} for k, v in filters.items() if v is not None]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}

def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(n, 1024)))
    p = 1024 ** i
    s = round(n / p, 2)
    return f"{s} {units[i]}"

def stable_doc_id(doc_bytes: bytes, filename: str) -> str:
    h = hashlib.sha256(); h.update(doc_bytes); h.update(filename.encode("utf-8"))
    return h.hexdigest()[:32]

def stable_chunk_id(doc_id: str, idx: int, text: str) -> str:
    h = hashlib.sha256(); h.update(doc_id.encode()); h.update(str(idx).encode()); h.update(text.encode())
    return h.hexdigest()[:32]

# ----------------------- Adapters -----------------------
class ChromaStore(VectorStore):
    """LangChain Chroma wrapper (default)."""
    def __init__(self, persist_dir: str = CHROMA_DIR):
        # from langchain.vectorstores import Chroma  # local import to avoid hard dep if unused
        self._Chroma = Chroma
        self.persist_dir = persist_dir
        self.db = self._Chroma(persist_directory=self.persist_dir, embedding_function=_get_embeddings())

    def upsert(self, rows: Iterable[VectorRecord]) -> None:
        docs: List[Document] = []
        ids: List[str] = []
        for r in rows:
            md = dict(r.metadata); md["doc_id"] = r.doc_id; md["chunk_id"] = r.chunk_id; md["__ns"] = VECTOR_NAMESPACE
            docs.append(Document(page_content=r.text, metadata=md))
            ids.append(r.chunk_id)
        self.db.add_documents(docs, ids=ids)
        self.db.persist()

    def delete_by_doc(self, doc_id: str) -> None:
        try:
            self.db.delete(where={"doc_id": doc_id, "__ns": VECTOR_NAMESPACE})
            self.db.persist()
        except Exception:
            log.exception("Chroma delete_by_doc failed")

    def search(self, query_embedding: List[float], top_k: int = 4,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[VectorRecord, float]]:
        try:
            where = _build_where_from_kv({**(filters or {}), "__ns": VECTOR_NAMESPACE})
            docs = self.db.similarity_search_by_vector(
                embedding=query_embedding,
                k=top_k,
                filter=where
            )
        except Exception:
            docs = []
        out: List[Tuple[VectorRecord, float]] = []
        for d in docs:
            md = dict(d.metadata or {})
            out.append((VectorRecord(
                doc_id=str(md.get("doc_id", "")),
                chunk_id=str(md.get("chunk_id", "")),
                text=d.page_content,
                embedding=[],
                metadata=md,
            ), 0.0))
        return out

    def flush(self) -> None:
        try:
            self.db.persist()
        except Exception:
            pass

    def stats(self) -> Dict[str, str]:
        base = os.path.abspath(self.persist_dir)
        total_size = 0
        total_files = 0
        last_mtime = 0
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for f in files:
                    total_files += 1
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        total_size += st.st_size
                        if st.st_mtime > last_mtime:
                            last_mtime = int(st.st_mtime)
                    except Exception:
                        pass
        return {
            "Chunks": f"~{total_files}",
            "Storage": _fmt_bytes(total_size),
            "Last Reindex": (
                datetime.utcfromtimestamp(last_mtime).isoformat() + "Z"
                if last_mtime else "n/a"
            ),
        }

class PgVectorStore(VectorStore):
    """Direct Postgres+pgvector adapter (no LangChain wrapper)."""
    def __init__(self, table: str = PGVECTOR_TABLE):
        self.table = table
        self._dim = EMBED_DIM
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {self.table} (
          doc_id   TEXT NOT NULL,
          chunk_id TEXT PRIMARY KEY,
          text     TEXT NOT NULL,
          metadata JSONB NOT NULL,
          embedding VECTOR({self._dim}) NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_{self.table}_doc ON {self.table}(doc_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table}_gin ON {self.table} USING gin (metadata);
        """
        with _session_scope() as s:
            # requires: CREATE EXTENSION IF NOT EXISTS vector;
            s.exec_driver_sql(ddl)
            s.commit()

    def upsert(self, rows: Iterable[VectorRecord]) -> None:
        sql = f"""
        INSERT INTO {self.table} (doc_id, chunk_id, text, metadata, embedding)
        VALUES (:doc_id, :chunk_id, :text, CAST(:md AS JSONB), :emb)
        ON CONFLICT (chunk_id) DO UPDATE SET
          doc_id=EXCLUDED.doc_id,
          text=EXCLUDED.text,
          metadata=EXCLUDED.metadata,
          embedding=EXCLUDED.embedding;
        """
        with _session_scope() as s:
            for r in rows:
                md = {**r.metadata, "__ns": VECTOR_NAMESPACE}
                s.exec_driver_sql(sql, {
                    "doc_id": r.doc_id,
                    "chunk_id": r.chunk_id,
                    "text": r.text,
                    "md": json.dumps(md),
                    "emb": r.embedding,
                })
            s.commit()

    def delete_by_doc(self, doc_id: str) -> None:
        with _session_scope() as s:
            s.exec_driver_sql(
                f"DELETE FROM {self.table} WHERE doc_id=:d AND (metadata->>'__ns')=:ns",
                {"d": doc_id, "ns": VECTOR_NAMESPACE},
            )
            s.commit()

    def search(self, query_embedding: List[float], top_k: int = 4,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[VectorRecord, float]]:
        where = ["(metadata->>'__ns')=:ns"]
        params: Dict[str, Any] = {"ns": VECTOR_NAMESPACE, "k": top_k, "q": query_embedding}
        if filters:
            i = 0
            for k, v in filters.items():
                safe_key = "".join(c for c in str(k) if c.isalnum() or c in "_-")
                where.append(f"(metadata->>'{safe_key}') = :f{i}")
                params[f"f{i}"] = str(v)
                i += 1
        where_sql = " AND ".join(where)
        sql = f"""
        SELECT doc_id, chunk_id, text, metadata::text, 1 - (embedding <=> :q) AS score
        FROM {self.table}
        WHERE {where_sql}
        ORDER BY embedding <=> :q
        LIMIT :k
        """
        with _session_scope() as s:
            rows = s.exec_driver_sql(sql, params).all()
        out: List[Tuple[VectorRecord, float]] = []
        for (doc_id, chunk_id, text, md_str, score) in rows:
            out.append((
                VectorRecord(doc_id=doc_id, chunk_id=chunk_id, text=text, embedding=[], metadata=json.loads(md_str)),
                float(score),
            ))
        return out

    def flush(self) -> None:
        return

    def stats(self) -> Dict[str, str]:
        try:
            with _session_scope() as s:
                cnt = s.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {self.table} WHERE (metadata->>'__ns')=:ns",
                    {"ns": VECTOR_NAMESPACE}
                ).scalar()
            return {"Chunks": str(cnt or 0), "Storage": "n/a", "Last Reindex": "n/a"}
        except Exception:
            return {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

class QdrantStore(VectorStore):
    """Qdrant adapter (works with Cloud URL+API key or self-hosted host/port)."""
    def __init__(self, collection: str = VECTOR_NAMESPACE):
        if qdrant_client is None:
            raise RuntimeError("qdrant-client not installed. `pip install qdrant-client`")

        url = os.getenv("QDRANT_URL")  # e.g., https://<cluster>.<region>.cloud.qdrant.io
        api_key = os.getenv("QDRANT_API_KEY")
        if url:
            self.client = qdrant_client.QdrantClient(url=url, api_key=api_key, prefer_grpc=False)
        else:
            host = os.getenv("QDRANT_HOST", "localhost")
            port = int(os.getenv("QDRANT_PORT", "6333"))
            self.client = qdrant_client.QdrantClient(host=host, port=port)

        self.collection = collection
        self._dim = EMBED_DIM

        # Ensure collection exists (idempotent)
        try:
            self.client.get_collection(self.collection)
        except Exception:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=self._dim, distance=qm.Distance.COSINE),
            )

        # Ensure required payload indexes exist (idempotent)
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self):
        index_specs = [
            ("__ns",       "keyword"),
            ("user_email", "keyword"),
            ("session_id", "keyword"),  # stored as string in our code
            ("user_id",    "keyword"),  # flip to "integer" if you truly store ints
            ("owner",      "keyword"),
            ("is_public",  "bool"),
            ("doc_id",     "keyword"),
            ("chunk_id",   "keyword"),
        ]
        for field, schema in index_specs:
            try:
                self.client.create_payload_index(collection_name=self.collection,
                                                 field_name=field,
                                                 field_schema=schema)
            except Exception as e:
                if "already exists" in str(e).lower():
                    continue
                # Qdrant Cloud returns 400 on wrong type: don't fail startup, just log.
                log.debug("Index create ignored for %s (%s): %s", field, schema, str(e)[:200])

    def _safe_search(self, **kwargs):
        """
        Wrap client.search: if Qdrant complains about a missing index, auto-create it and retry once.
        """
        try:
            return self.client.search(**kwargs)
        except UnexpectedResponse as e:
            msg = str(e)
            # Try to extract the missing field name from error: "Index required but not found for \"__ns\" ..."
            m = re.search(r'Index required but not found for \\\?"([^"\\]+)\\\?"', msg) or \
                re.search(r'Index required but not found for "([^"]+)"', msg)
            if m:
                missing = m.group(1)
                # Default to keyword; this is safe for most of our string filters
                try:
                    self.client.create_payload_index(collection_name=self.collection,
                                                     field_name=missing,
                                                     field_schema="keyword")
                    log.warning("Auto-created missing Qdrant index for key=%s", missing)
                    return self.client.search(**kwargs)
                except Exception as ce:
                    log.error("Failed to auto-create payload index for %s: %s", missing, ce)
            raise

    def upsert(self, rows: Iterable[VectorRecord]) -> None:
        points = []
        for r in rows:
            payload = {"doc_id": r.doc_id, "chunk_id": r.chunk_id, "__ns": VECTOR_NAMESPACE, **r.metadata, "text": r.text}
            points.append(qm.PointStruct(id=r.chunk_id, vector=r.embedding, payload=payload))
        self.client.upsert(collection_name=self.collection, points=points)

    def delete_by_doc(self, doc_id: str) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(must=[
                    qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)),
                    qm.FieldCondition(key="__ns", match=qm.MatchValue(value=VECTOR_NAMESPACE)),
                ])
            ),
        )

    def search(self, query_embedding: List[float], top_k: int = 4,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[VectorRecord, float]]:
        conds = [qm.FieldCondition(key="__ns", match=qm.MatchValue(value=VECTOR_NAMESPACE))]
        for k, v in (filters or {}).items():
            # Skip None values; keep as strings/bools as provided
            if v is None:
                continue
            conds.append(qm.FieldCondition(key=str(k), match=qm.MatchValue(value=v)))
        res = self._safe_search(
            collection_name=self.collection,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=qm.Filter(must=conds) if conds else None,
        )
        out: List[Tuple[VectorRecord, float]] = []
        for r in res:
            p = dict(r.payload or {})
            out.append((
                VectorRecord(
                    doc_id=str(p.get("doc_id", "")),
                    chunk_id=str(p.get("chunk_id", "")),
                    text=str(p.get("text", "")),
                    embedding=[],
                    metadata=p,
                ),
                float(r.score),
            ))
        return out

    def flush(self) -> None:
        self.client.flush(collection_name=self.collection)

    def stats(self) -> Dict[str, str]:
        try:
            info = self.client.get_collection(self.collection)
            vectors = getattr(info, "points_count", None) or getattr(info, "vectors_count", None)
            return {"Chunks": str(vectors or "n/a"), "Storage": "n/a", "Last Reindex": "n/a"}
        except Exception:
            return {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

# ----------------------- Factory + Dual-write Service -----------------------
def _make_store(name: str) -> VectorStore:
    if name == "chroma":
        return ChromaStore()
    if name == "pgvector":
        return PgVectorStore()
    if name == "qdrant":
        return QdrantStore()
    raise ValueError(f"Unknown vector backend: {name}")

PRIMARY: Optional[VectorStore] = None
SHADOWS: List[VectorStore] = []

def _ensure_initialized() -> None:
    global PRIMARY, SHADOWS
    if PRIMARY is not None:
        return

    log.warning(f"VECTOR DIM USING: {EMBED_DIM} model={EMBED_MODEL}")

    primary_name = VECTOR_PRIMARY
    PRIMARY = _make_store(primary_name)
    SHADOWS.clear()
    for s in VECTOR_SHADOWS:
        if not s:
            continue
        try:
            SHADOWS.append(_make_store(s))
        except Exception:
            log.exception("Failed to init shadow backend: %s", s)
    log.info("Vector service initialized. primary=%s shadows=%s shadow_read=%s",
             type(PRIMARY).__name__,
             ",".join(type(s).__name__ for s in SHADOWS) or "-",
             VECTOR_SHADOW_READ)

def _embed_texts(texts: List[str]) -> List[List[float]]:
    return _get_embeddings().embed_documents(texts)

def _embed_query(text: str) -> List[float]:
    return _get_embeddings().embed_query(text)

def _dual_write(rows: Iterable[VectorRecord]) -> None:
    rows = list(rows)
    PRIMARY.upsert(rows)
    for s in SHADOWS:
        try:
            s.upsert(rows)
        except Exception:
            log.exception("Shadow upsert failed")

def _shadow_compare(query_embedding: List[float], top_k: int, filters: Optional[Dict[str, Any]]):
    if not VECTOR_SHADOW_READ or not SHADOWS:
        return
    p = PRIMARY.search(query_embedding, top_k, filters)
    p_ids = [r.chunk_id for (r, _) in p]
    for s in SHADOWS:
        try:
            s_res = s.search(query_embedding, top_k, filters)
            s_ids = [r.chunk_id for (r, _) in s_res]
            if p_ids != s_ids:
                log.warning("Shadow drift: primary=%s vs %s=%s", p_ids, type(s).__name__, s_ids)
        except Exception:
            log.exception("Shadow search failed")

# ----------------------- Public API (kept compatible) -----------------------
def embed_and_store(user_email: str, text: str, metadata: Optional[Dict] = None):
    """
    Splits text, embeds chunks, and writes to the configured vector backend(s).
    Maintains your current signature/behavior and metadata keys (user_email, session_id, etc).
    """
    _ensure_initialized()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(text)

    normalized = _normalize_metadata(metadata)
    if user_email:
        normalized = {**normalized, "user_email": user_email}

    embeddings = _embed_texts(chunks)

    # We don't generate a doc_id from bytes here because we only have `text`
    doc_id = normalized.get("doc_id") or hashlib.sha256(
        (":" + (normalized.get("filename") or "") + ":" + text[:2048]).encode()
    ).hexdigest()[:32]

    records: List[VectorRecord] = []
    for i, (txt, emb) in enumerate(zip(chunks, embeddings)):
        cid = stable_chunk_id(doc_id, i, txt)
        md = {**normalized, "doc_id": doc_id, "chunk_id": cid}
        records.append(VectorRecord(
            doc_id=doc_id,
            chunk_id=cid,
            text=txt,
            embedding=emb,
            metadata=md,
        ))

    _dual_write(records)

def query_user_docs(
    user_email: str,
    question: str,
    top_k: int = 4,
    filter_by_user: bool = True,
    extra_filters: Optional[Dict] = None
) -> List[Document]:
    """
    Returns a list of LangChain `Document` objects for compatibility with your current call sites.
    Works for Chroma, pgvector, and Qdrant.
    """
    _ensure_initialized()

    ef = _normalize_metadata(extra_filters)
    filters: Dict[str, Any] = {"__ns": VECTOR_NAMESPACE}
    if ef:
        filters.update(ef)
    # Keep your existing semantics:
    if filter_by_user or (ef and "session_id" in ef):
        filters["user_email"] = user_email

    # Chroma fast-path: text similarity with metadata filter
    if isinstance(PRIMARY, ChromaStore):
        try:
            # from langchain.vectorstores import Chroma  # noqa
            where = _build_where_from_kv(filters)
            db = PRIMARY.db  # type: ignore[attr-defined]
            return db.similarity_search(question, k=top_k, filter=where)  # List[Document]
        except Exception:
            return []

    # Non-Chroma path: embed query → vector search → convert to Documents
    qvec = _embed_query(question)
    try:
        hits = PRIMARY.search(qvec, top_k=top_k, filters=filters)
        _shadow_compare(qvec, top_k, filters)
    except Exception:
        log.exception("Primary search failed")
        return []

    docs: List[Document] = []
    for rec, _score in hits:
        docs.append(Document(page_content=rec.text, metadata={**rec.metadata, "doc_id": rec.doc_id, "chunk_id": rec.chunk_id}))
    return docs

def get_vector_stats() -> Dict[str, str]:
    """
    Keeps your original shape but adapts per-backend.
    """
    _ensure_initialized()
    try:
        return PRIMARY.stats()
    except Exception:
        # Chroma-compatible fallback
        base = os.path.abspath(CHROMA_DIR)
        total_size = 0
        total_files = 0
        last_mtime = 0
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for f in files:
                    total_files += 1
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        total_size += st.st_size
                        if st.st_mtime > last_mtime:
                            last_mtime = int(st.st_mtime)
                    except Exception:
                        pass
        return {
            "Chunks": f"~{total_files}",
            "Storage": _fmt_bytes(total_size),
            "Last Reindex": (
                datetime.utcfromtimestamp(last_mtime).isoformat() + "Z"
                if last_mtime else "n/a"
            ),
        }

# ----------------------- Public API (search shim for retrieval) -----------------------
# ----------------------- Public API (search shim for retrieval) -----------------------
async def search_vectors(
    question: Optional[str] = None,
    query: Optional[str] = None,
    top_k: Optional[int] = None,
    k: Optional[int] = None,
    filters: Optional[Dict[str, Any]] = None,
    scope: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Back-compat shim expected by app.services.query_engine.retrieval.

    Accepts both legacy and new arg names:
      - text:  question | query
      - k:     top_k    | k
      - where: filters  | scope

    Returns a list of dicts with keys: doc_id, chunk_id, text, meta, score.
    """
    _ensure_initialized()

    # Normalize args from either naming style
    q = (question or query or "").strip()
    if not q:
        return []

    topk = int(top_k if top_k is not None else (k if k is not None else 10))

    # Merge filters/scope (retrieval.py passes a prebuilt scope dict)
    f: Dict[str, Any] = {}
    if filters:
        f.update(filters)
    if scope:
        f.update(scope)

    # Ensure some ids are strings for backends that index as keywords
    for key in ("session_id", "user_id"):
        if key in f and f[key] is not None:
            f[key] = str(f[key])

    # Embed query and run ANN on primary store
    qvec = _embed_query(q)
    try:
        hits = PRIMARY.search(qvec, top_k=topk, filters=f)
    except Exception:
        log.exception("search_vectors: primary search failed")
        return []

    out: List[Dict[str, Any]] = []
    for rec, score in hits:
        out.append({
            "doc_id":   rec.doc_id,
            "chunk_id": rec.chunk_id,
            "text":     rec.text,
            "meta":     dict(rec.metadata or {}),
            "score":    float(score) if score is not None else 0.0,
        })
    return out


# def search_vectors(
#     question: str,
#     top_k: int = 10,
#     filters: Optional[Dict[str, Any]] = None,
# ) -> List[Dict[str, Any]]:
#     """
#     Back-compat shim expected by app.services.query_engine.retrieval.
#     - Embeds the query
#     - Runs ANN search on the configured PRIMARY store
#     - Returns a list of dicts with keys: doc_id, chunk_id, text, meta, score

#     NOTE: This does NOT do BM25; lexical is handled elsewhere (retrieval module).
#     """
#     _ensure_initialized()

#     # Normalize filters; leave values as-is except ensure some keys are strings
#     f: Dict[str, Any] = {}
#     if filters:
#         for k, v in filters.items():
#             if k in ("session_id", "user_id") and v is not None:
#                 f[k] = str(v)
#             else:
#                 f[k] = v

#     qvec = _embed_query(question)
#     try:
#         hits = PRIMARY.search(qvec, top_k=top_k, filters=f)
#     except Exception:
#         log.exception("search_vectors: primary search failed")
#         return []

#     out: List[Dict[str, Any]] = []
#     for rec, score in hits:
#         out.append({
#             "doc_id":   rec.doc_id,
#             "chunk_id": rec.chunk_id,
#             "text":     rec.text,
#             "meta":     dict(rec.metadata or {}),
#             "score":    float(score) if score is not None else 0.0,
#         })
#     return out

# ----------------------- Optional: Healthcheck -----------------------
def vector_healthcheck() -> Dict[str, Any]:
    """Upserts a small test vector into each configured store and verifies it can be read back."""
    _ensure_initialized()
    results: Dict[str, Any] = {}
    stores = [("primary", PRIMARY)] + [(f"shadow_{i}", s) for i, s in enumerate(SHADOWS, 1)]
    for name, store in stores:
        try:
            cid = f"_hc_{name}_{int(time.time())}"
            vec = [0.002] * EMBED_DIM
            rec = VectorRecord(doc_id=cid, chunk_id=cid, text="hc", embedding=vec, metadata={})
            store.upsert([rec])
            hits = store.search(vec, top_k=5, filters={"__ns": VECTOR_NAMESPACE})
            ok = any(r.chunk_id == cid for r, _ in hits)
            results[name] = {"store": type(store).__name__, "ok": ok}
        except Exception as e:
            results[name] = {"store": type(store).__name__, "ok": False, "error": str(e)}
    return results
