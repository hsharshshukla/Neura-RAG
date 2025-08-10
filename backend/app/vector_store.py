# app/vector_store.py — Handles vector embedding and metadata-filtered retrieval
from typing import List, Dict, Optional, Any
from langchain.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import os
from dotenv import load_dotenv

load_dotenv()

CHROMA_DIR = "vector_store"
embeddings = OpenAIEmbeddings()

def _normalize_metadata(md: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure consistent types for metadata stored in Chroma."""
    md = (md or {}).copy()
    # We store session_id as string for consistent filtering later
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
        # normalize types, e.g., ensure session_id is a string
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

    # Only include user_email when filter_by_user is True (free tier behavior)
    where = _build_chroma_where(user_email if filter_by_user else None, extra_filters)

    # LangChain passes this 'filter' through to Chroma's 'where'
    return vectordb.similarity_search(question, k=top_k, filter=where)
