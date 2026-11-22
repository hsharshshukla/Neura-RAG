from __future__ import annotations

from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.deps.workspace import WorkspaceAccess, require_tkp_workspace_access
from app.integrations.tkp.client import TKPIngestionClient
from app.integrations.tkp.config import TKPSettings
from app.middleware.security import CSRFMiddleware
from app.models import User
from app.routes.admin_bulk_upload import router


def _app(upstream, role: str = "owner") -> tuple[FastAPI, TestClient, TKPIngestionClient, Session]:
    settings = TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        ingestion_service_token=SecretStr("write-only-test-token-987654321"),
        staging_workspace_id=uuid4(),
        environment="test",
    )
    bridge = TKPIngestionClient(settings, transport=httpx.MockTransport(upstream))
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    db = Session(engine)
    user = User(id=1, email="owner@example.test", role="admin")
    db.add(user)
    db.commit()

    app = FastAPI()
    app.state.tkp_ingestion_client = bridge
    app.add_middleware(CSRFMiddleware)
    app.include_router(router)

    access = WorkspaceAccess(user=user, workspace_id=settings.staging_workspace_id, role=role)
    app.dependency_overrides[require_tkp_workspace_access] = lambda: access
    app.dependency_overrides[get_session] = lambda: db
    return app, TestClient(app), bridge, db


def test_bulk_upload_enforces_role_and_rejects_forged_scope() -> None:
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"detail": "secret"})

    app, client, bridge, db = _app(upstream, role="reader")
    response = client.post(
        "/api/v1/admin/bulk-upload",
        files={"files": ("report.pdf", b"contents", "application/pdf")},
    )
    db.close()
    assert response.status_code == 403
    assert calls == 0


def _workflow_response(job_id, workspace_id, correlation_id):
    return httpx.Response(
        201,
        json={
            "job": {
                "id": str(job_id),
                "workspace_id": str(workspace_id),
                "source_id": str(uuid4()),
                "source_version_id": str(uuid4()),
                "status": "AWAITING_APPROVAL",
                "processing_status": "COMPLETED",
                "index_status": "NOT_READY",
                "retryable": False,
            },
            "reused": False,
            "correlation_id": str(correlation_id),
        },
    )


def test_bulk_upload_uses_phase7a_workflow_and_distinguishes_states() -> None:
    async def upstream(request: httpx.Request) -> httpx.Response:
        correlation = request.headers["x-correlation-id"]
        if request.url.path == "/api/v1/document-workflows":
            return _workflow_response(uuid4(), uuid4(), correlation)
        return httpx.Response(200, json={})

    app, client, bridge, db = _app(upstream)
    client.cookies.set("access_token", "session")
    client.cookies.set("csrf_token", "csrf-value")
    response = client.post(
        "/api/v1/admin/bulk-upload",
        files=[
            ("files", ("one.pdf", b"one", "application/pdf")),
            ("files", ("two.txt", b"two", "text/plain")),
        ],
        data={"workspace_id": str(uuid4()), "owner_id": "attacker"},
        headers={"X-CSRF-Token": "csrf-value"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 2
    assert body["processing_complete"] is True
    assert body["search_index_ready"] is False
    job_id = body["job_id"]

    foreign_app = FastAPI()
    foreign_app.state.tkp_ingestion_client = bridge
    foreign_app.include_router(router)
    foreign_app.dependency_overrides[get_session] = lambda: db
    foreign_app.dependency_overrides[require_tkp_workspace_access] = lambda: WorkspaceAccess(
        user=User(id=2, email="other@example.test", role="admin"),
        workspace_id=uuid4(),
        role="owner",
    )
    foreign = TestClient(foreign_app)
    assert foreign.get(f"/api/v1/admin/bulk-upload/{job_id}").status_code == 404
    db.close()
