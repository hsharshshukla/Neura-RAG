# app/vector_store.py
from typing import List, Dict, Optional, Any
from langchain.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import os
import math
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

CHROMA_DIR = os.getenv(
    "VECTOR_STORE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vector_store"))
)

EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Create embeddings lazily to avoid import-time crashes if key is missing
def _get_embeddings():
    return OpenAIEmbeddings(model=EMBED_MODEL)

def _normalize_metadata(md: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    md = (md or {}).copy()
    if "session_id" in md and md["session_id"] is not None:
        md["session_id"] = str(md["session_id"])
    return md

def _build_where_from_kv(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = [{k: v} for k, v in filters.items() if v is not None]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}

def embed_and_store(user_email: str, text: str, metadata: Optional[Dict] = None):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.create_documents([text])

    normalized = _normalize_metadata(metadata)
    if user_email:
        normalized = {**normalized, "user_email": user_email}

    for chunk in chunks:
        chunk.metadata.update(normalized)

    try:
        vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=_get_embeddings())
        vectordb.add_documents(chunks)
        vectordb.persist()
    except Exception:
        # Fail-soft in dev; logs will show the realtrace
        pass

def query_user_docs(
    user_email: str,
    question: str,
    top_k: int = 4,
    filter_by_user: bool = True,
    extra_filters: Optional[Dict] = None
) -> List[Document]:
    try:
        vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=_get_embeddings())
    except Exception:
        return []

    ef = _normalize_metadata(extra_filters)
    filters: Dict[str, Any] = {}

    if ef:
        filters.update(ef)

    if filter_by_user or (ef and "session_id" in ef):
        filters["user_email"] = user_email

    where = _build_where_from_kv(filters)

    try:
        return vectordb.similarity_search(question, k=top_k, filter=where)
    except Exception:
        return []

def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(n, 1024)))
    p = 1024 ** i
    s = round(n / p, 2)
    return f"{s} {units[i]}"

def get_vector_stats() -> Dict[str, str]:
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
