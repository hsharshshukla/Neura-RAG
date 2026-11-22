from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
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
from app.models import TKPBulkUploadDocument, TKPBulkUploadJob, User
from app.routes.admin_bulk_upload import router


def _metadata_response(
    correlation_id: str,
    document: TKPBulkUploadDocument,
    workspace_id: UUID,
    *,
    state: str = "DRAFT",
    mode: str = "LOW_CONFIDENCE",
    review_required: bool = True,
) -> dict:
    now = datetime.now(UTC).isoformat()
    verification_id = UUID("10000000-0000-4000-8000-000000000001")
    submission_id = UUID("20000000-0000-4000-8000-000000000002")
    event_id = UUID("30000000-0000-4000-8000-000000000003")
    source_id = UUID(document.source_id or "")
    version_id = UUID(document.source_version_id or "")
    return {
        "metadata_verification": {
            "verification": {
                "id": str(verification_id),
                "workspace_id": str(workspace_id),
                "source_id": str(source_id),
                "version_id": str(version_id),
                "source_file_id": str(uuid4()),
                "extraction_id": str(uuid4()),
                "revision_number": 1,
                "document_sha256": "a" * 64,
                "document_format": "PDF",
                "original_filename": document.filename,
                "submission_id": str(submission_id),
                "request_hash": "b" * 64,
                "exact_input_hash": "c" * 64,
                "policy": {
                    "policy_id": "document-metadata-default",
                    "version": "1",
                    "mode": mode,
                    "confidence_threshold": 0.8,
                    "confidence_values": {"title": 0.91, "document_type": None},
                    "required_fields": ["title"],
                    "defaults": {},
                    "field_rules": {
                        "title": {"value_type": "STRING", "allowed_values": []},
                        "document_type": {
                            "value_type": "STRING",
                            "allowed_values": ["PDF", "DOCX", "TXT"],
                        },
                    },
                },
                "review_required": review_required,
                "review_fields": ["title"],
                "selected_fields": ["title", "document_type"],
                "initial_draft": {"title": "Extracted title", "document_type": "PDF"},
                "contract_version": "document-metadata-verification-v1",
                "created_by": str(uuid4()),
                "created_at": now,
            },
            "verification_state": state,
            "index_state": "NOT_READY",
            "version": 1,
            "draft": {"title": "Draft title", "document_type": "PDF"},
            "history": [
                {
                    "id": str(event_id),
                    "workspace_id": str(workspace_id),
                    "verification_id": str(verification_id),
                    "sequence_number": 1,
                    "action": "CREATED",
                    "submission_id": str(submission_id),
                    "request_hash": "b" * 64,
                    "exact_input_hash": "c" * 64,
                    "draft": {"title": "Draft title", "document_type": "PDF"},
                    "actor_id": str(uuid4()),
                    "created_at": now,
                }
            ],
        },
        "correlation_id": correlation_id,
    }


def _app(upstream):
    workspace_id = uuid4()
    settings = TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        ingestion_service_token=SecretStr("write-only-test-token-987654321"),
        staging_workspace_id=workspace_id,
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
    owner = User(id=1, email="owner@example.test", role="admin")
    db.add(owner)
    job = TKPBulkUploadJob(
        id=str(uuid4()), workspace_id=str(workspace_id), owner_user_id=owner.id
    )
    document = TKPBulkUploadDocument(
        id=str(uuid4()),
        bulk_job_id=job.id,
        workspace_id=str(workspace_id),
        owner_user_id=owner.id,
        filename="source.pdf",
        tkp_job_id=str(uuid4()),
        source_id=str(uuid4()),
        source_version_id=str(uuid4()),
        processing_status="COMPLETED",
        index_status="NOT_READY",
    )
    db.add(job)
    db.add(document)
    db.commit()

    access = {
        "value": WorkspaceAccess(user=owner, workspace_id=workspace_id, role="owner")
    }
    app = FastAPI()
    app.state.tkp_ingestion_client = bridge
    app.add_middleware(CSRFMiddleware)
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[require_tkp_workspace_access] = lambda: access["value"]
    return TestClient(app), bridge, db, access, job, document, workspace_id


def test_review_uses_actual_tkp_contract_and_enforces_owner_scope() -> None:
    calls: list[httpx.Request] = []
    context: dict = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer write-only-test-token-987654321"
        return httpx.Response(
            200,
            json=_metadata_response(
                request.headers["x-correlation-id"],
                context["document"],
                context["workspace_id"],
            ),
        )

    client, bridge, db, access, job, document, workspace_id = _app(upstream)
    context.update(document=document, workspace_id=workspace_id)
    path = f"/api/v1/admin/bulk-upload/{job.id}/documents/{document.id}/metadata-review"
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert calls[0].url.path == (
        f"/api/v1/sources/{document.source_id}/versions/"
        f"{document.source_version_id}/metadata-verification"
    )
    assert body["review"]["verification_status"] == "DRAFT"
    assert body["review"]["index_status"] == "NOT_READY"
    assert body["review"]["review_fields"][0]["original_value"] == "Extracted title"
    assert body["review"]["review_fields"][0]["required"] is True
    assert body["review"]["verification_mode"] == "LOW_CONFIDENCE"
    assert body["review"]["confidence_threshold"] == 0.8
    assert body["review"]["selected_fields"] == [
        {"key": "title", "confidence": 0.91, "confidence_supplied": True},
        {"key": "document_type", "confidence": None, "confidence_supplied": True},
    ]
    assert body["review"]["derived_review_fields"] == ["title"]
    assert body["review"]["review_fields"][0]["confidence"] == 0.91
    assert "tkp.internal" not in response.text

    access["value"] = WorkspaceAccess(
        user=User(id=2, email="other@example.test", role="admin"),
        workspace_id=uuid4(),
        role="owner",
    )
    assert client.get(path).status_code == 404
    assert len(calls) == 1
    db.close()
    client.close()


@pytest.mark.parametrize(
    ("mode", "review_required"),
    [("NEVER", True), ("ALWAYS", False)],
)
def test_review_not_required_has_no_editable_fields_or_actions(
    mode: str, review_required: bool
) -> None:
    context: dict = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_metadata_response(
                request.headers["x-correlation-id"],
                context["document"],
                context["workspace_id"],
                mode=mode,
                review_required=review_required,
            ),
        )

    client, bridge, db, access, job, document, workspace_id = _app(upstream)
    context.update(document=document, workspace_id=workspace_id)
    path = f"/api/v1/admin/bulk-upload/{job.id}/documents/{document.id}/metadata-review"
    response = client.get(path)
    assert response.status_code == 200
    review = response.json()["review"]
    assert review["reviewable"] is False
    assert review["no_review_required"] is True
    assert review["review_fields"] == []
    assert review["derived_review_fields"] == []
    assert review["allowed_actions"] == []
    assert len(review["selected_fields"]) == 2
    db.close()
    client.close()


def test_submit_requires_csrf_and_calls_only_actual_submit_transition() -> None:
    calls: list[httpx.Request] = []
    context: dict = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=_metadata_response(
                request.headers["x-correlation-id"],
                context["document"],
                context["workspace_id"],
                state="VERIFIED",
            ),
        )

    client, bridge, db, access, job, document, workspace_id = _app(upstream)
    context.update(document=document, workspace_id=workspace_id)
    path = (
        f"/api/v1/admin/bulk-upload/{job.id}/documents/{document.id}"
        "/metadata-review/submit"
    )
    payload = {
        "expected_version": 1,
        "submission_id": str(uuid4()),
        "values": {"title": "browser value must not reach submit"},
    }
    client.cookies.set("access_token", "session")
    client.cookies.set("csrf_token", "csrf-value")
    assert client.post(path, json=payload).status_code == 403
    response = client.post(path, json=payload, headers={"X-CSRF-Token": "csrf-value"})
    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0].method == "GET"
    assert calls[1].url.path.endswith(
        "/document-metadata-verifications/10000000-0000-4000-8000-000000000001/submit"
    )
    assert json.loads(calls[1].content) == {
        "submission_id": payload["submission_id"],
        "expected_version": 1,
    }
    db.close()
    client.close()


def test_start_draft_and_preview_use_exact_paths_and_payloads() -> None:
    calls: list[httpx.Request] = []
    context: dict = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/original"):
            return httpx.Response(
                200,
                content=b"%PDF-test",
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": 'inline; filename="source.pdf"',
                    "X-TKP-Source-Sha256": "a" * 64,
                },
            )
        return httpx.Response(
            200,
            json=_metadata_response(
                request.headers["x-correlation-id"],
                context["document"],
                context["workspace_id"],
            ),
        )

    client, bridge, db, access, job, document, workspace_id = _app(upstream)
    context.update(document=document, workspace_id=workspace_id)
    base = f"/api/v1/admin/bulk-upload/{job.id}/documents/{document.id}/metadata-review"
    client.cookies.set("access_token", "session")
    client.cookies.set("csrf_token", "csrf-value")
    headers = {"X-CSRF-Token": "csrf-value"}

    assert client.post(base + "/start", json={}, headers=headers).status_code == 200
    assert calls[0].method == "POST"
    assert calls[0].url.path.endswith(
        f"/sources/{document.source_id}/versions/{document.source_version_id}/metadata-verification"
    )
    assert UUID(json.loads(calls[0].content)["submission_id"])

    draft = {
        "expected_version": 1,
        "submission_id": str(uuid4()),
        "values": {"title": "Reviewed", "document_type": "PDF"},
    }
    assert client.post(base + "/save-draft", json=draft, headers=headers).status_code == 200
    assert calls[2].method == "PUT"
    assert calls[2].url.path.endswith("/draft")
    assert json.loads(calls[2].content)["changes"] == draft["values"]

    preview = client.get(base + "/original")
    assert preview.status_code == 200
    assert preview.content == b"%PDF-test"
    assert calls[3].url.path.endswith(
        f"/sources/{document.source_id}/versions/{document.source_version_id}/original"
    )
    db.close()
    client.close()


def test_review_fails_closed_for_invalid_upstream_and_forged_scope() -> None:
    calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "metadata_verification": {"version": 1},
                "correlation_id": request.headers["x-correlation-id"],
            },
        )

    client, bridge, db, access, job, document, workspace_id = _app(upstream)
    path = f"/api/v1/admin/bulk-upload/{job.id}/documents/{document.id}/metadata-review"
    assert client.get(path).status_code == 502
    payload = {
        "expected_version": 1,
        "submission_id": str(uuid4()),
        "values": {},
        "workspace_id": str(uuid4()),
    }
    assert client.post(path + "/verify", json=payload).status_code == 422
    assert calls == 1
    db.close()
    client.close()
