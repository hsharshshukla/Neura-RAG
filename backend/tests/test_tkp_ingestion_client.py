from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.integrations.tkp.client import TKPClientError, TKPIngestionClient
from app.integrations.tkp.config import TKPSettings


def _settings(**changes) -> TKPSettings:
    values = {
        "internal_url": "https://tkp.internal",
        "service_token": SecretStr("read-only-test-token-123456789"),
        "ingestion_service_token": SecretStr("write-only-test-token-987654321"),
        "staging_workspace_id": uuid4(),
        "environment": "test",
    }
    values.update(changes)
    return TKPSettings(**values)


@pytest.mark.asyncio
async def test_ingestion_uses_write_credential_and_phase7a_workflow_contract() -> None:
    settings = _settings()
    correlation_id = uuid4()
    job_id = uuid4()
    source_id = uuid4()
    source_version_id = uuid4()
    captured: dict[str, object] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured.update(
            path=request.url.path,
            authorization=request.headers["authorization"],
            correlation=request.headers["x-correlation-id"],
            body=request.content,
        )
        return httpx.Response(
            202,
            json={
                "job": {
                    "id": str(job_id),
                    "workspace_id": str(settings.staging_workspace_id),
                    "source_id": str(source_id),
                    "source_version_id": str(source_version_id),
                    "status": "QUEUED",
                    "processing_status": "QUEUED",
                    "index_status": "NOT_READY",
                },
                "reused": False,
                "correlation_id": str(correlation_id),
            },
        )

    client = TKPIngestionClient(settings, transport=httpx.MockTransport(upstream))
    try:
        response = await client.start_document_workflow(
            "safe.pdf",
            __import__("io").BytesIO(b"document"),
            "application/pdf",
            correlation_id,
        )
    finally:
        await client.aclose()

    body = captured["body"]
    assert isinstance(body, bytes)
    assert response["job"]["id"] == str(job_id)
    assert captured["path"] == "/api/v1/document-workflows"
    assert captured["authorization"] == "Bearer write-only-test-token-987654321"
    assert "read-only-test-token" not in str(captured["authorization"])
    assert captured["correlation"] == str(correlation_id)
    assert b"safe.pdf" in body
    assert b"TROUBLESHOOTING" in body
    assert b"neura:" in body


@pytest.mark.asyncio
async def test_ingestion_status_preserves_tkp_provenance_and_readiness() -> None:
    correlation_id = uuid4()
    job_id = uuid4()
    source_id = uuid4()
    source_version_id = uuid4()
    revision_id = uuid4()

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": str(job_id),
                    "workspace_id": str(uuid4()),
                    "source_id": str(source_id),
                    "source_version_id": str(source_version_id),
                    "status": "AWAITING_APPROVAL",
                    "processing_status": "COMPLETED",
                    "index_status": "NOT_READY",
                    "retryable": False,
                    "revision_id": str(revision_id),
                },
                "reused": False,
                "correlation_id": str(correlation_id),
            },
        )

    client = TKPIngestionClient(_settings(), transport=httpx.MockTransport(upstream))
    try:
        status = await client.document_workflow_status(str(job_id), correlation_id)
    finally:
        await client.aclose()

    job = status["job"]
    assert job["source_version_id"] == str(source_version_id)
    assert job["revision_id"] == str(revision_id)
    assert job["processing_status"] == "COMPLETED"
    assert job["index_status"] == "NOT_READY"


def test_retrieval_and_ingestion_credentials_cannot_be_reused() -> None:
    with pytest.raises(ValidationError, match="must be different"):
        _settings(
            ingestion_service_token=SecretStr("read-only-test-token-123456789")
        )


@pytest.mark.asyncio
async def test_ingestion_authorization_failure_is_sanitized() -> None:
    correlation_id = uuid4()

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "secret credential diagnostic"})

    client = TKPIngestionClient(_settings(), transport=httpx.MockTransport(upstream))
    with pytest.raises(TKPClientError) as caught:
        await client.start_document_workflow(
            "report.pdf",
            __import__("io").BytesIO(b"document"),
            "application/pdf",
            correlation_id,
        )
    await client.aclose()

    assert caught.value.code == "TKP_AUTHORIZATION_FAILED"
    assert "secret credential diagnostic" not in caught.value.public_message
    assert caught.value.correlation_id == correlation_id
