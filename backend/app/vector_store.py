# app/vector_store.py — Handles vector embedding and metadata-filtered retrieval
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

# Resolve a stable absolute directory for Chroma persistence.
# You can override with VECTOR_STORE_DIR in backend/.env
CHROMA_DIR = os.getenv(
    "VECTOR_STORE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vector_store"))
)

embeddings = OpenAIEmbeddings()

def _normalize_metadata(md: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure consistent types for metadata stored in Chroma."""
    md = (md or {}).copy()
    # Store session_id as string for consistent filtering later
    if "session_id" in md and md["session_id"] is not None:
        md["session_id"] = str(md["session_id"])
    return md

def _build_chroma_where(
    user_email: Optional[str],
    extra_filters: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Build a Chroma 'where' filter.
    Chroma requires exactly one top-level operator when there is >1 condition.
    We use {'$and': [ ...clauses... ]} for multiple clauses.
    """
    clauses: List[Dict[str, Any]] = []

    if user_email:
        clauses.append({"user_email": user_email})

    if extra_filters:
        ef = _normalize_metadata(extra_filters)
        for k, v in ef.items():
            clauses.append({k: v})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}

def embed_and_store(user_email: str, text: str, metadata: Optional[Dict] = None):
    """
    Split text, attach metadata, and persist to Chroma.
    Ensure metadata is normalized (e.g., session_id stored as string).
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.create_documents([text])

    normalized = _normalize_metadata(metadata)
    # Always store the user_email so we can filter by it
    if user_email:
        normalized = {**normalized, "user_email": user_email}

    for chunk in chunks:
        chunk.metadata.update(normalized)

    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    vectordb.add_documents(chunks)
    vectordb.persist()

def query_user_docs(
    user_email: str,
    question: str,
    top_k: int = 4,
    filter_by_user: bool = True,
    extra_filters: Optional[Dict] = None
) -> List[Document]:
    """
    Query Chroma with an optional user scope and extra filters (e.g., session_id).
    """
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    where = _build_chroma_where(user_email if filter_by_user else None, extra_filters)
    # LangChain passes this 'filter' through to Chroma's 'where'
    return vectordb.similarity_search(question, k=top_k, filter=where)

# -----------------------
# Admin dashboard helpers
# -----------------------

def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(n, 1024)))
    p = 1024 ** i
    s = round(n / p, 2)
    return f"{s} {units[i]}"

def get_vector_stats() -> Dict[str, str]:
    """
    Returns a coarse storage summary for the admin dashboard:
    - approximate file count (Chunks)
    - total on-disk size (Storage)
    - latest modification time under the vector dir (Last Reindex)
    """
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
                    # ignore unreadable files
                    pass

    return {
        "Chunks": f"~{total_files}",
        "Storage": _fmt_bytes(total_size),
        "Last Reindex": (
            datetime.utcfromtimestamp(last_mtime).isoformat() + "Z"
            if last_mtime else "n/a"
        ),
    }


