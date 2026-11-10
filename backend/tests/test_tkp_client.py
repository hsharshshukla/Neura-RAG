from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.tkp.client import TKPClient, TKPClientError
from app.integrations.tkp.config import TKPSettings
from app.integrations.tkp.schemas import BrowserRetrievalRequest, TKPRetrievalRequest


def _settings(**changes) -> TKPSettings:
    values = {
        "internal_url": "https://tkp.internal",
        "service_token": SecretStr("read-only-test-token-123456789"),
        "staging_workspace_id": uuid4(),
        "environment": "test",
        "max_attempts": 2,
        "retry_base_seconds": 0,
        "retry_max_seconds": 0,
    }
    values.update(changes)
    return TKPSettings(**values)


def _response(correlation_id: UUID, *, results: list[dict] | None = None) -> dict:
    projection_id = uuid4()
    article_id = uuid4()
    revision_id = uuid4()
    fragment_id = uuid4()
    result = {
        "rank": 1,
        "projection_id": str(projection_id),
        "projection_type": "TROUBLESHOOTING",
        "title": "Approved fix",
        "question": None,
        "content": "Use the approved procedure.",
        "retrieval_text": "approved procedure",
        "matches": [{"kind": "FULL_TEXT", "value": None}],
        "product_names": ["Product X"],
        "product_versions": ["4.2"],
        "related_technologies": [],
        "exact_terms": [],
        "knowledge_scope": "VERSION_SPECIFIC",
        "resolution_status": "CONFIRMED",
        "article_id": str(article_id),
        "revision_id": str(revision_id),
        "claim_references": [
            {
                "revision_claim_id": str(uuid4()),
                "candidate_claim_id": str(uuid4()),
                "source_fragment_ids": [str(fragment_id)],
            }
        ],
        "hierarchy": None,
        "graph": None,
        "ranking": {
            "rrf_k": 60,
            "rrf_score": 0.1,
            "exact_identifier_bonus": 0,
            "final_score": 0.1,
            "contributions": [
                {
                    "strategy": "LEXICAL",
                    "rank": 1,
                    "reciprocal_rank_score": 0.1,
                    "backend_score": 0.5,
                }
            ],
        },
    }
    selected = [result] if results is None else results
    return {
        "analysis": {"classifications": ["GENERAL_LOOKUP"]},
        "plan": {
            "strategy": "LEXICAL",
            "selected_strategies": ["LEXICAL"],
            "routing_reasons": ["default"],
            "graph_relationships_supported": False,
            "retrieval_configuration": "ROUTED",
        },
        "results": selected,
        "backend_status": [
            {
                "strategy": "LEXICAL",
                "backend": "postgresql",
                "attempted": True,
                "available": True,
                "degraded": False,
                "deadline_seconds": 5,
                "result_count": len(selected),
                "calls": 1,
                "latency_ms": 2,
            }
        ],
        "total": len(selected),
        "limit": 10,
        "offset": 0,
        "has_more": False,
        "backend_calls": 1,
        "correlation_id": str(correlation_id),
    }


@pytest.mark.asyncio
async def test_search_preserves_lineage_and_forces_safe_backend_configuration() -> None:
    correlation_id = uuid4()
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["correlation"] = request.headers["x-correlation-id"]
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=_response(correlation_id))

    client = TKPClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        request = TKPRetrievalRequest.from_browser(
            BrowserRetrievalRequest(query="approved Product X fix")
        )
        response = await client.search(request, correlation_id)
    finally:
        await client.aclose()

    result = response.results[0]
    assert result.projection_id
    assert result.article_id
    assert result.revision_id
    assert result.claim_references[0].candidate_claim_id
    assert result.claim_references[0].source_fragment_ids
    assert captured["correlation"] == str(correlation_id)
    assert captured["authorization"].startswith("Bearer ")
    assert captured["json"]["retrieval_configuration"] == "ROUTED"
    assert captured["json"]["experimental_opensearch"] is False
    assert captured["json"]["vector_search_mode"] == "EXACT"
    assert "workspace_id" not in captured["json"]
    assert "source_version_ids" not in captured["json"]


@pytest.mark.asyncio
async def test_retry_is_bounded_for_retryable_status() -> None:
    correlation_id = uuid4()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                json={
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "unavailable",
                    "correlation_id": str(correlation_id),
                    "details": None,
                },
            )
        return httpx.Response(200, json=_response(correlation_id, results=[]))

    client = TKPClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        result = await client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    finally:
        await client.aclose()
    assert calls == 2
    assert result.results == ()


@pytest.mark.asyncio
async def test_authorization_failure_is_not_retried_or_leaked() -> None:
    correlation_id = uuid4()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            json={
                "code": "ACCESS_DENIED",
                "message": "credential detail must not escape",
                "correlation_id": str(correlation_id),
            },
        )

    client = TKPClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(TKPClientError) as caught:
        await client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    await client.aclose()
    assert calls == 1
    assert caught.value.code == "TKP_AUTHORIZATION_FAILED"
    assert "credential detail" not in caught.value.public_message


@pytest.mark.asyncio
async def test_contract_mismatch_fails_closed() -> None:
    correlation_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"content": "partial"}]})

    client = TKPClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(TKPClientError, match="TKP_RESPONSE_INVALID"):
        await client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_total_deadline_maps_to_typed_timeout() -> None:
    correlation_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json=_response(correlation_id))

    client = TKPClient(
        _settings(total_deadline_seconds=0.01, connect_timeout_seconds=0.005, max_attempts=1),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(TKPClientError) as caught:
        await client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    await client.aclose()
    assert caught.value.code == "TKP_TIMEOUT"
    assert caught.value.status_code == 504


@pytest.mark.asyncio
async def test_httpx_timeout_is_not_mislabeled_as_unavailable() -> None:
    correlation_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read deadline", request=request)

    client = TKPClient(_settings(max_attempts=1), transport=httpx.MockTransport(handler))
    with pytest.raises(TKPClientError) as caught:
        await client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    await client.aclose()
    assert caught.value.code == "TKP_TIMEOUT"


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_without_retry() -> None:
    correlation_id = uuid4()
    started = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200, json=_response(correlation_id))

    client = TKPClient(_settings(max_attempts=3), transport=httpx.MockTransport(handler))
    task = asyncio.create_task(
        client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client.aclose()
    assert calls == 1


@pytest.mark.asyncio
async def test_degraded_backend_status_is_preserved() -> None:
    correlation_id = uuid4()
    body = _response(correlation_id)
    body["backend_status"][0].update(
        {"degraded": True, "fallback_backend": "postgres", "reason": "optional backend disabled"}
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = TKPClient(_settings(max_attempts=1), transport=httpx.MockTransport(handler))
    try:
        result = await client.search(
            TKPRetrievalRequest.from_browser(BrowserRetrievalRequest(query="x")),
            correlation_id,
        )
    finally:
        await client.aclose()
    assert result.backend_status[0].degraded is True
    assert result.backend_status[0].fallback_backend == "postgres"
    assert result.backend_status[0].reason == "optional backend disabled"
