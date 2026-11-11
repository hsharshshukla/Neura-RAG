# app/lifespan.py
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from pydantic import ValidationError

# Optional: reuse your bootstrap helpers instead of reimplementing
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.integrations.tkp.client import TKPClient
from app.integrations.tkp.config import get_tkp_settings

log = logging.getLogger("neura.lifespan")


def validate_rate_limit_storage(environment: str) -> None:
    """Require a networked Redis service for multi-instance environments."""
    if environment not in {"staging", "prod"}:
        return
    redis_url = os.getenv("REDIS_URL", "").strip()
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise RuntimeError(
            "Staging and production require a shared redis:// or rediss:// rate-limit store"
        )


def _qdrant_bootstrap_once() -> None:
    """
    Creates the collection and payload indexes if they don't exist.
    Runs at process start only when QDRANT_BOOTSTRAP_ON_START=true.
    """
    collection = os.getenv("VECTOR_NAMESPACE", "prod")
    dim = int(os.getenv("EMBED_DIM", "1536"))

    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if url:
        client = QdrantClient(url=url, api_key=api_key, prefer_grpc=False, timeout=20.0)
    else:
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=host, port=port, timeout=20.0)

    # Ensure collection
    try:
        client.get_collection(collection)
        log.info("Qdrant collection %s exists", collection)
    except Exception:
        client.create_collection(
            collection_name=collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        log.info("Qdrant collection %s created", collection)

    # Ensure payload indexes only once
    specs = [
        ("__ns", "keyword"),
        ("user_email", "keyword"),
        ("session_id", "keyword"),
        ("user_id", "keyword"),
        ("owner", "keyword"),
        ("is_public", "bool"),
        ("doc_id", "keyword"),
        ("chunk_id", "keyword"),
    ]
    for field, schema in specs:
        try:
            client.create_payload_index(
                collection_name=collection, field_name=field, field_schema=schema
            )
            log.info("[ok] created payload index %s (%s)", field, schema)
        except Exception as e:
            # Qdrant returns 409/AlreadyExists — treat as idempotent
            if "already exists" in str(e).lower():
                log.debug("[skip] index %s exists", field)
            else:
                raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup and once on shutdown for the whole process.
    Use this to:
      - (optionally) bootstrap Qdrant collection/indexes
      - warm/init vector store client(s)
    """
    environment = os.getenv("APP_ENV", "dev").lower()
    organizational_mode = os.getenv("ORGANIZATIONAL_RAG_MODE", "legacy").lower()
    if environment in {"staging", "prod"} and organizational_mode != "tkp":
        raise RuntimeError("ORGANIZATIONAL_RAG_MODE=tkp is required outside development")
    validate_rate_limit_storage(environment)

    app.state.tkp_client = None
    try:
        app.state.tkp_client = TKPClient(get_tkp_settings())
    except ValidationError:
        if environment in {"staging", "prod"} or organizational_mode == "tkp":
            raise RuntimeError("Complete TKP bridge configuration is required") from None
        log.info("TKP bridge is not configured in this development environment")

    # 1) Bootstrap legacy indexes only when the explicitly selected mode needs them.
    if (
        organizational_mode == "legacy"
        and os.getenv("QDRANT_BOOTSTRAP_ON_START", "false").lower() == "true"
    ):
        try:
            _qdrant_bootstrap_once()
        except Exception as e:
            # Don't crash the app: log; your /health can reflect degraded state if desired
            log.exception("Qdrant bootstrap failed: %s", e)

    # 2) Warm up vector store once (so requests don’t do it)
    if organizational_mode == "legacy":
        try:
            from app.vector_store import (
                _ensure_initialized,  # lazy import to avoid side-effects
            )

            _ensure_initialized()
            log.info("Vector store initialized in lifespan.")
        except Exception as e:
            log.exception("Vector store init failed: %s", e)

    # 3) (optional) any other warmups: load prompts, templates, etc.

    try:
        yield  # ---- app runs here ----
    finally:
        if app.state.tkp_client is not None:
            await app.state.tkp_client.aclose()

    # graceful shutdown hooks (optional)
    # e.g., closing clients, flushing telemetry, etc.
