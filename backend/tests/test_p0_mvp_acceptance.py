"""Opt-in final P0 acceptance against disposable real infrastructure.

Run from the registered TKP virtual environment with its integration conftest loaded.
This test never invokes TKP ingestion. It seeds approved knowledge through the TKP
test-domain service, then exposes the actual TKP FastAPI retrieval endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

TKP_ROOT = Path(os.environ["TKP_REPOSITORY_ROOT"]).resolve()
NEURA_BACKEND = Path(os.environ["NEURA_BACKEND_ROOT"]).resolve()
NEURA_PYTHON = Path(os.environ["NEURA_PYTHON"]).resolve()
EVIDENCE_PATH = Path(os.environ["P0_EVIDENCE_PATH"]).resolve()
_hold_value = os.environ.get("P0_BROWSER_HOLD_PATH", "").strip()
_ready_value = os.environ.get("P0_BROWSER_READY_PATH", "").strip()
HOLD_PATH = Path(_hold_value).resolve() if _hold_value else None
READY_PATH = Path(_ready_value).resolve() if _ready_value else None

if str(TKP_ROOT) not in sys.path:
    sys.path.insert(0, str(TKP_ROOT))

from apps.api.main import create_app  # noqa: E402
from tests.integration.test_knowledge_search import _archive_index  # noqa: E402
from tkp.domain.access import ConfiguredCredential  # noqa: E402

pytestmark = pytest.mark.integration

OWNER_EMAIL = "p0-owner@example.test"
OWNER_PASSWORD = secrets.token_urlsafe(32)
SHARED_BYTES = b"Shared identical bytes for both tenant deployments."
TENANT_A_BYTES = b"Private tenant A canary: AURORA-COPPER-71."
TENANT_B_BYTES = b"Private tenant B canary: BOREAL-SILVER-29."
INDEX_FIELDS = {
    "__ns": "keyword",
    "user_email": "keyword",
    "user_id": "keyword",
    "session_id": "keyword",
    "doc_id": "keyword",
    "chunk_id": "keyword",
    "attachment_kind": "keyword",
    "sha256": "keyword",
}


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


async def _wait_http(base_url: str, process: asyncio.subprocess.Process | None = None) -> None:
    async with httpx.AsyncClient(base_url=base_url) as client:
        for _ in range(500):
            if process is not None and process.returncode is not None:
                output, _ = await process.communicate()
                pytest.fail("service exited during startup:\n" + output.decode(errors="replace"))
            try:
                if (await client.get("/health", timeout=0.25)).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)
    pytest.fail(f"service did not become ready: {base_url}")


@asynccontextmanager
async def _serve_tkp(app: Any):
    port = _free_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(2048)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(500):
        if server.started:
            break
        if task.done():
            await task
        await asyncio.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def _dsn(postgres: PostgresContainer, database: str, *, driver: str = "psycopg") -> str:
    return URL.create(
        f"postgresql+{driver}",
        username=postgres.username,
        password=postgres.password,
        host=postgres.get_container_host_ip(),
        port=int(postgres.get_exposed_port(5432)),
        database=database,
        query={"sslmode": "disable"} if driver == "psycopg" else {},
    ).render_as_string(hide_password=False)


def _run_neura(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NEURA_PYTHON), *args],
        cwd=NEURA_BACKEND,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _tenant_env(
    *,
    dsn: str,
    namespace: str,
    storage: Path,
    qdrant_port: int,
    redis_port: int,
    tkp_url: str,
    tkp_token: str,
    workspace_id: str,
    frontend_origin: str,
    port: int,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(NEURA_BACKEND),
            "PYTHONDONTWRITEBYTECODE": "1",
            "APP_ENV": "test",
            "DATABASE_URL": dsn,
            "ALEMBIC_URL": dsn,
            "JWT_SECRET": secrets.token_urlsafe(32),
            "COOKIE_SECURE": "false",
            "COOKIE_SAMESITE": "lax",
            "REQUIRE_EMAIL_VERIFICATION": "false",
            "ORGANIZATIONAL_RAG_MODE": "tkp",
            "VECTOR_PRIMARY": "qdrant",
            "VECTOR_SHADOWS": "",
            "VECTOR_NAMESPACE": namespace,
            "QDRANT_HOST": "127.0.0.1",
            "QDRANT_PORT": str(qdrant_port),
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "EMBED_DIM": "1536",
            "STORAGE_BACKEND": "local",
            "DOC_STORAGE_PATH": str(storage),
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "TKP_INTERNAL_URL": tkp_url,
            "TKP_SERVICE_TOKEN": tkp_token,
            "TKP_STAGING_WORKSPACE_ID": workspace_id,
            "TKP_ENVIRONMENT": "test",
            "TKP_MAX_ATTEMPTS": "1",
            "TKP_TOTAL_DEADLINE_SECONDS": "10",
            "TKP_CHAT_RETRIEVAL_LIMIT": "10",
            "OPENAI_MODEL_PRO": "gpt-5.4-mini",
            "CHAT_MODEL": "gpt-5.4-mini",
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "acceptance-provider-double"),
            "CORS_ALLOWED_ORIGINS": frontend_origin,
            "P0_PROVIDER_MODE": os.getenv("P0_PROVIDER_MODE", "deterministic"),
            "P0_NEURA_PORT": str(port),
            "ANALYTICS_DISABLED": "true",
        }
    )
    return env


def _seed(env: dict[str, str], workspace_id: str) -> None:
    code = f"""
import os
from datetime import datetime
from sqlmodel import Session
from app.db import engine
from app.models import ChatSession, User, Workspace, WorkspaceMembership
from app.utils.security import get_password_hash
with Session(engine) as session:
    user = User(id=1, email={OWNER_EMAIL!r}, password=get_password_hash(os.environ["P0_TEST_OWNER_PASSWORD"]),
                tier='pro', email_verified_at=datetime.utcnow())
    workspace = Workspace(id={workspace_id!r}, name='P0 disposable TKP workspace')
    session.add(user); session.add(workspace); session.commit()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=1, role='reader'))
    session.add(ChatSession(id=1, user_id=1, workspace_id=workspace.id, title='P0 acceptance'))
    session.commit()
print('seeded')
"""
    seed_env = {**env, "P0_TEST_OWNER_PASSWORD": OWNER_PASSWORD}
    assert _run_neura("-c", code, env=seed_env).stdout.strip().endswith("seeded")


async def _prepare_qdrant(base_url: str, namespace: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        for _ in range(120):
            try:
                if (await client.get("/healthz", timeout=0.5)).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.25)
        else:
            pytest.fail("Qdrant did not become ready")
        response = await client.put(
            f"/collections/{namespace}",
            json={"vectors": {"size": 1536, "distance": "Cosine"}},
        )
        assert response.status_code in {200, 409}, response.text
        for field, schema in INDEX_FIELDS.items():
            response = await client.put(
                f"/collections/{namespace}/index?wait=true",
                json={"field_name": field, "field_schema": schema},
            )
            assert response.status_code in {200, 409}, response.text


async def _tkp_projection_count(database) -> int:
    async with database.session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM knowledge_projections"))
        return int(result.scalar_one())


async def _login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        data={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert client.cookies.get("access_token")
    csrf = client.cookies.get("csrf_token")
    assert csrf
    return csrf


async def _upload(
    client: httpx.AsyncClient, csrf: str, filename: str, content: bytes
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/upload",
        data={"session_id": "1"},
        files={"file": (filename, content, "text/plain")},
        headers={"X-CSRF-Token": csrf, "X-Content-Digest": hashlib.sha256(content).hexdigest()},
        timeout=30,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _duplicate(client: httpx.AsyncClient, content: bytes) -> bool:
    response = await client.get(
        "/api/v1/upload/check",
        params={
            "session_id": 1,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        },
    )
    assert response.status_code == 200, response.text
    return bool(response.json()["duplicate"])


async def _stream(client: httpx.AsyncClient, csrf: str, message: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/chat/stream",
        json={"message": message, "session_id": 1, "request_id": str(uuid4())},
        headers={"X-CSRF-Token": csrf},
        timeout=40,
    )
    assert response.status_code == 200, response.text
    events: dict[str, Any] = {"answer": "", "citations": [], "complete": None}
    for block in response.text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        lines = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        event = lines["event"].strip()
        data = json.loads(lines["data"].strip())
        if event == "answer":
            events["answer"] += data["chunk"]
        elif event == "citations":
            events["citations"] = data["citations"]
        elif event == "complete":
            events["complete"] = data
        elif event == "error":
            pytest.fail(f"stream error: {data}")
    assert events["complete"]
    return events


@pytest.mark.asyncio
async def test_final_p0_mvp_integration_acceptance(database, migrated_settings, tmp_path):
    owner, canonical, _ = await _archive_index(database, migrated_settings)
    tkp_token = secrets.token_urlsafe(32)
    credential = ConfiguredCredential(
        actor_id=owner.actor_id,
        workspace_id=owner.workspace_id,
        permissions=frozenset({"knowledge:read"}),
        token=SecretStr(tkp_token),
    )
    tkp_app = create_app(
        migrated_settings.model_copy(update={"ingestion_credentials": [credential]})
    )
    evidence: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "provider_mode": os.getenv("P0_PROVIDER_MODE", "deterministic"),
        "tkp": {"article_id": str(canonical.article.id), "ingestion_exercised": False},
    }

    with (
        PostgresContainer(
            "postgres:16", username="neura", password=secrets.token_urlsafe(32), dbname="tenant_a"
        ) as postgres,
        DockerContainer("qdrant/qdrant:v1.15.1").with_exposed_ports(6333) as qdrant,
        DockerContainer("redis:7-alpine").with_exposed_ports(6379) as redis,
    ):
        admin_dsn = _dsn(postgres, "tenant_a", driver="asyncpg")
        engine = create_async_engine(admin_dsn, isolation_level="AUTOCOMMIT")
        async with engine.connect() as connection:
            await connection.execute(text('CREATE DATABASE "tenant_b"'))
        await engine.dispose()

        qdrant_port = int(qdrant.get_exposed_port(6333))
        redis_port = int(redis.get_exposed_port(6379))
        qdrant_url = f"http://127.0.0.1:{qdrant_port}"
        namespaces = {"a": "p0_mvp_tenant_a", "b": "p0_mvp_tenant_b"}
        for namespace in namespaces.values():
            await _prepare_qdrant(qdrant_url, namespace)

        async with _serve_tkp(tkp_app) as tkp_url:
            tkp_before = await _tkp_projection_count(database)
            ports = {"a": _free_port(), "b": _free_port()}
            frontend_port = _free_port()
            frontend_origin = f"http://127.0.0.1:{frontend_port}"
            envs = {
                tenant: _tenant_env(
                    dsn=_dsn(postgres, f"tenant_{tenant}"),
                    namespace=namespaces[tenant],
                    storage=tmp_path / f"storage-{tenant}",
                    qdrant_port=qdrant_port,
                    redis_port=redis_port,
                    tkp_url=tkp_url,
                    tkp_token=tkp_token,
                    workspace_id=str(owner.workspace_id),
                    frontend_origin=frontend_origin,
                    port=ports[tenant],
                )
                for tenant in ("a", "b")
            }
            for env in envs.values():
                _run_neura("-m", "alembic", "-c", "alembic.ini", "upgrade", "head", env=env)
                _seed(env, str(owner.workspace_id))

            processes = {
                tenant: await asyncio.create_subprocess_exec(
                    str(NEURA_PYTHON),
                    str(NEURA_BACKEND / "tests" / "p0_acceptance_neura_runner.py"),
                    cwd=NEURA_BACKEND,
                    env=envs[tenant],
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                for tenant in ("a", "b")
            }
            try:
                for tenant, process in processes.items():
                    await _wait_http(f"http://127.0.0.1:{ports[tenant]}", process)

                clients = {
                    tenant: httpx.AsyncClient(base_url=f"http://127.0.0.1:{ports[tenant]}")
                    for tenant in ("a", "b")
                }
                try:
                    csrf = {tenant: await _login(clients[tenant]) for tenant in ("a", "b")}

                    # Browser preflight includes the attachment digest header fixed by this P0.
                    preflight = await clients["a"].options(
                        "/api/v1/upload",
                        headers={
                            "Origin": frontend_origin,
                            "Access-Control-Request-Method": "POST",
                            "Access-Control-Request-Headers": (
                                "content-type,x-csrf-token,x-content-digest,x-requested-with"
                            ),
                        },
                    )
                    assert preflight.status_code == 200, preflight.text
                    allowed = preflight.headers["access-control-allow-headers"].lower()
                    assert "x-content-digest" in allowed and "x-csrf-token" in allowed

                    assert not await _duplicate(clients["a"], SHARED_BYTES)
                    assert not await _duplicate(clients["b"], SHARED_BYTES)
                    shared = {
                        tenant: await _upload(
                            clients[tenant], csrf[tenant], "shared.txt", SHARED_BYTES
                        )
                        for tenant in ("a", "b")
                    }
                    assert shared["a"]["doc_id"] == shared["b"]["doc_id"]
                    assert shared["a"]["duplicate"] is False
                    assert shared["b"]["duplicate"] is False
                    assert await _duplicate(clients["a"], SHARED_BYTES)
                    assert await _duplicate(clients["b"], SHARED_BYTES)
                    repeat = await _upload(clients["a"], csrf["a"], "shared.txt", SHARED_BYTES)
                    assert repeat["duplicate"] is True

                    private = {
                        "a": await _upload(
                            clients["a"], csrf["a"], "tenant-a.txt", TENANT_A_BYTES
                        ),
                        "b": await _upload(
                            clients["b"], csrf["b"], "tenant-b.txt", TENANT_B_BYTES
                        ),
                    }
                    assert private["a"]["doc_id"] != private["b"]["doc_id"]

                    combined = await _stream(
                        clients["a"],
                        csrf["a"],
                        "Use archive.war organizational evidence and AURORA-COPPER-71 attachment evidence.",
                    )
                    attachment_citations = [
                        item for item in combined["citations"]
                        if item.get("attachment_kind") == "conversation_attachment"
                    ]
                    organizational_citations = [
                        item for item in combined["citations"]
                        if item.get("article_id") == str(canonical.article.id)
                    ]
                    assert attachment_citations and organizational_citations
                    assert any(
                        item["document_id"] == private["a"]["doc_id"]
                        for item in attachment_citations
                    )

                    isolated = await _stream(
                        clients["a"],
                        csrf["a"],
                        "Find the forbidden BOREAL-SILVER-29 tenant B canary.",
                    )
                    assert "BOREAL-SILVER-29" not in isolated["answer"]
                    assert all(
                        item.get("document_id") != private["b"]["doc_id"]
                        for item in isolated["citations"]
                    )

                    cross_session = await clients["a"].get(
                        "/api/v1/upload/check",
                        params={
                            "session_id": 2,
                            "sha256": hashlib.sha256(TENANT_A_BYTES).hexdigest(),
                            "size": len(TENANT_A_BYTES),
                        },
                    )
                    assert cross_session.status_code == 404

                    tkp_after = await _tkp_projection_count(database)
                    assert tkp_after == tkp_before

                    async with httpx.AsyncClient(base_url=qdrant_url) as qclient:
                        index_evidence = {}
                        for tenant, namespace in namespaces.items():
                            info = (await qclient.get(f"/collections/{namespace}")).json()
                            schema = info["result"]["payload_schema"]
                            assert set(INDEX_FIELDS) <= set(schema)
                            index_evidence[tenant] = sorted(schema)

                    evidence.update(
                        {
                            "result": "PASS",
                            "qdrant": {
                                "version": "1.15.1",
                                "namespaces": namespaces,
                                "payload_indexes": index_evidence,
                                "embedding_dimension": 1536,
                            },
                            "tenants": {
                                "database_names": ["tenant_a", "tenant_b"],
                                "user_ids": [1, 1],
                                "session_ids": [1, 1],
                                "shared_doc_id_equal": True,
                                "private_doc_ids": {
                                    "a": private["a"]["doc_id"],
                                    "b": private["b"]["doc_id"],
                                },
                            },
                            "combined_citations": {
                                "organizational": len(organizational_citations),
                                "attachment": len(attachment_citations),
                            },
                            "cors_digest_header_allowed": True,
                            "tkp_projection_count_unchanged": tkp_after == tkp_before,
                            "browser": {
                                "url": frontend_origin,
                                "backend": f"http://127.0.0.1:{ports['a']}",
                                "email": OWNER_EMAIL,
                            },
                        }
                    )
                    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    EVIDENCE_PATH.write_text(
                        json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
                    )

                    if READY_PATH is not None:
                        READY_PATH.write_text(
                            json.dumps(
                                {
                                    "frontend_port": frontend_port,
                                    "backend_port": ports["a"],
                                    "email": OWNER_EMAIL,
                                    "password": OWNER_PASSWORD,
                                }
                            ),
                            encoding="utf-8",
                        )
                    if HOLD_PATH is not None:
                        deadline = time.monotonic() + 900
                        while not HOLD_PATH.exists() and time.monotonic() < deadline:
                            await asyncio.sleep(0.25)
                        assert HOLD_PATH.exists(), "browser acceptance hold timed out"
                finally:
                    for client in clients.values():
                        await client.aclose()
            finally:
                for process in processes.values():
                    process.terminate()
                for process in processes.values():
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10)
                    except TimeoutError:
                        process.kill()
                        await asyncio.wait_for(process.wait(), timeout=5)

    evidence["finished_at"] = datetime.now(UTC).isoformat()
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
