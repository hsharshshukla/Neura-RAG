from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from app.integrations.tkp.config import TKPSettings
from app.integrations.tkp.schemas import (
    TKPDocumentWorkflowResponse,
    TKPErrorBody,
    TKPRetrievalRequest,
    TKPRetrievalResponse,
)

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class TKPClientError(Exception):
    code: str
    public_message: str
    correlation_id: UUID
    status_code: int = 503
    upstream_status: int | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.code


class TKPClient:
    """Typed async TKP client with one total deadline and bounded safe retries."""

    _PATH = "/api/v1/knowledge/retrieval/search"
    _RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        settings: TKPSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._jitter = jitter
        self._http = httpx.AsyncClient(
            base_url=str(settings.internal_url).rstrip("/"),
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=settings.write_timeout_seconds,
                pool=settings.pool_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ready(self, correlation_id: UUID) -> bool:
        try:
            response = await asyncio.wait_for(
                self._http.get(
                    "/health/ready",
                    headers={"X-Correlation-ID": str(correlation_id)},
                ),
                timeout=self._settings.total_deadline_seconds,
            )
        except (TimeoutError, httpx.TransportError):
            return False
        return response.status_code == 200

    async def search(
        self, request: TKPRetrievalRequest, correlation_id: UUID
    ) -> TKPRetrievalResponse:
        last_error: TKPClientError | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.total_deadline_seconds

        for attempt in range(1, self._settings.max_attempts + 1):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                response = await asyncio.wait_for(
                    self._http.post(
                        self._PATH,
                        json=request.model_dump(mode="json"),
                        headers={
                            "Authorization": (
                                "Bearer " + self._settings.service_token.get_secret_value()
                            ),
                            "X-Correlation-ID": str(correlation_id),
                        },
                    ),
                    timeout=remaining,
                )
                if response.status_code == 200:
                    try:
                        parsed = TKPRetrievalResponse.model_validate(response.json())
                    except (ValidationError, ValueError) as exc:
                        raise TKPClientError(
                            code="TKP_RESPONSE_INVALID",
                            public_message="Knowledge retrieval returned an incompatible response",
                            correlation_id=correlation_id,
                            status_code=502,
                        ) from exc
                    if parsed.correlation_id != correlation_id:
                        raise TKPClientError(
                            code="TKP_CORRELATION_MISMATCH",
                            public_message="Knowledge retrieval response could not be verified",
                            correlation_id=correlation_id,
                            status_code=502,
                        )
                    return parsed

                error = self._map_http_error(response, correlation_id)
                if not error.retryable:
                    raise error
                last_error = error
            except asyncio.CancelledError:
                raise
            except (TimeoutError, httpx.TimeoutException):
                last_error = TKPClientError(
                    code="TKP_TIMEOUT",
                    public_message="Knowledge retrieval timed out",
                    correlation_id=correlation_id,
                    status_code=504,
                    retryable=True,
                )
            except httpx.TransportError:
                last_error = TKPClientError(
                    code="TKP_UNAVAILABLE",
                    public_message="Knowledge retrieval is temporarily unavailable",
                    correlation_id=correlation_id,
                    status_code=503,
                    retryable=True,
                )

            if attempt < self._settings.max_attempts:
                cap = min(
                    self._settings.retry_max_seconds,
                    self._settings.retry_base_seconds * (2 ** (attempt - 1)),
                )
                delay = cap * (0.5 + self._jitter() * 0.5)
                remaining = deadline - loop.time()
                if delay >= remaining:
                    break
                await self._sleep(delay)

        raise last_error or TKPClientError(
            code="TKP_TIMEOUT",
            public_message="Knowledge retrieval timed out",
            correlation_id=correlation_id,
            status_code=504,
        )

    def _map_http_error(self, response: httpx.Response, correlation_id: UUID) -> TKPClientError:
        upstream_correlation = correlation_id
        upstream_code = "TKP_UPSTREAM_ERROR"
        try:
            body = TKPErrorBody.model_validate(response.json())
            upstream_correlation = body.correlation_id
            upstream_code = body.code
        except (ValidationError, ValueError):
            pass

        status = response.status_code
        if status in {401, 403}:
            return TKPClientError(
                code="TKP_AUTHORIZATION_FAILED",
                public_message="Knowledge retrieval is not authorized",
                correlation_id=upstream_correlation,
                status_code=503,
                upstream_status=status,
            )
        if status in {409, 422}:
            return TKPClientError(
                code="TKP_REQUEST_REJECTED",
                public_message="Knowledge retrieval request was rejected",
                correlation_id=upstream_correlation,
                status_code=502,
                upstream_status=status,
            )
        retryable = status in self._RETRYABLE_STATUSES
        return TKPClientError(
            code=upstream_code if retryable else "TKP_UPSTREAM_ERROR",
            public_message="Knowledge retrieval is temporarily unavailable",
            correlation_id=upstream_correlation,
            status_code=503 if retryable else 502,
            upstream_status=status,
            retryable=retryable,
        )


class TKPIngestionClient:
    """Write-only TKP client using a credential distinct from retrieval."""

    _WORKFLOW_PATH = "/api/v1/document-workflows"

    def __init__(
        self,
        settings: TKPSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.ingestion_service_token is None:
            raise ValueError("TKP ingestion credential is not configured")
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=str(settings.internal_url).rstrip("/"),
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=settings.write_timeout_seconds,
                pool=settings.pool_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def limits(self, correlation_id: UUID) -> dict[str, Any]:
        del correlation_id
        return {
            "limits": {
                "max_files": self._settings.bulk_max_files,
                "max_file_size_bytes": self._settings.bulk_max_file_bytes,
                "max_total_size_bytes": self._settings.bulk_max_total_bytes,
                "allowed_extensions": list(self._settings.bulk_allowed_extensions),
            }
        }

    async def start_document_workflow(
        self,
        filename: str,
        stream: BinaryIO,
        content_type: str,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        submission_id = uuid4()
        item = {
            "submission_id": str(submission_id),
            "source_key": f"neura:{submission_id}",
            "retry": False,
        }
        body = await self._request(
            "POST",
            self._WORKFLOW_PATH,
            correlation_id,
            data={"item": __import__("json").dumps(item), "candidate_type": "TROUBLESHOOTING"},
            files={"file": (filename, stream, content_type)},
        )
        try:
            response = TKPDocumentWorkflowResponse.model_validate(body)
        except ValidationError as exc:
            raise TKPClientError(
                code="TKP_RESPONSE_INVALID",
                public_message="Knowledge ingestion returned an incompatible response",
                correlation_id=correlation_id,
                status_code=502,
            ) from exc
        if response.correlation_id != correlation_id:
            raise TKPClientError(
                code="TKP_CORRELATION_MISMATCH",
                public_message="Knowledge ingestion response could not be verified",
                correlation_id=correlation_id,
                status_code=502,
            )
        return response.model_dump(mode="json")

    async def document_workflow_status(
        self, job_id: str, correlation_id: UUID
    ) -> dict[str, Any]:
        body = await self._request(
            "GET", f"{self._WORKFLOW_PATH}/{self._job_segment(job_id)}", correlation_id
        )
        try:
            response = TKPDocumentWorkflowResponse.model_validate(body)
        except ValidationError as exc:
            raise TKPClientError(
                code="TKP_RESPONSE_INVALID",
                public_message="Knowledge ingestion returned an incompatible response",
                correlation_id=correlation_id,
                status_code=502,
            ) from exc
        return response.model_dump(mode="json")

    async def retry_document_workflow(
        self,
        job_id: str,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        body = await self._request(
            "POST",
            f"{self._WORKFLOW_PATH}/{self._job_segment(job_id)}/retry",
            correlation_id,
        )
        try:
            response = TKPDocumentWorkflowResponse.model_validate(body)
        except ValidationError as exc:
            raise TKPClientError(
                code="TKP_RESPONSE_INVALID",
                public_message="Knowledge ingestion returned an incompatible response",
                correlation_id=correlation_id,
                status_code=502,
            ) from exc
        return response.model_dump(mode="json")

    @staticmethod
    def _job_segment(job_id: str) -> str:
        value = job_id.strip()
        if not value or len(value) > 200:
            raise TKPClientError(
                code="TKP_REQUEST_REJECTED",
                public_message="The ingestion job identifier is invalid",
                correlation_id=UUID(int=0),
                status_code=400,
            )
        return quote(value, safe="")

    async def _request(
        self,
        method: str,
        path: str,
        correlation_id: UUID,
        **kwargs: Any,
    ) -> dict[str, Any]:
        token = self._settings.ingestion_service_token
        if token is None:  # Defensive: configuration can never grant retrieval credentials writes.
            raise TKPClientError(
                code="TKP_INGESTION_NOT_CONFIGURED",
                public_message="Knowledge ingestion is not configured",
                correlation_id=correlation_id,
            )
        try:
            response = await asyncio.wait_for(
                self._http.request(
                    method,
                    path,
                    headers={
                        "Authorization": "Bearer " + token.get_secret_value(),
                        "X-Correlation-ID": str(correlation_id),
                    },
                    **kwargs,
                ),
                timeout=self._settings.total_deadline_seconds,
            )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise TKPClientError(
                code="TKP_TIMEOUT",
                public_message="Knowledge ingestion timed out",
                correlation_id=correlation_id,
                status_code=504,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise TKPClientError(
                code="TKP_UNAVAILABLE",
                public_message="Knowledge ingestion is temporarily unavailable",
                correlation_id=correlation_id,
                status_code=503,
                retryable=True,
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise _ingestion_http_error(response, correlation_id)
        try:
            body = response.json()
        except ValueError as exc:
            raise TKPClientError(
                code="TKP_RESPONSE_INVALID",
                public_message="Knowledge ingestion returned an incompatible response",
                correlation_id=correlation_id,
                status_code=502,
            ) from exc
        if not isinstance(body, dict):
            raise TKPClientError(
                code="TKP_RESPONSE_INVALID",
                public_message="Knowledge ingestion returned an incompatible response",
                correlation_id=correlation_id,
                status_code=502,
            )
        upstream_correlation = body.get("correlation_id")
        if upstream_correlation is not None and str(upstream_correlation) != str(correlation_id):
            raise TKPClientError(
                code="TKP_CORRELATION_MISMATCH",
                public_message="Knowledge ingestion response could not be verified",
                correlation_id=correlation_id,
                status_code=502,
            )
        return body


def _ingestion_http_error(response: httpx.Response, correlation_id: UUID) -> TKPClientError:
    if response.status_code in {401, 403}:
        return TKPClientError(
            code="TKP_AUTHORIZATION_FAILED",
            public_message="Knowledge ingestion is not authorized",
            correlation_id=correlation_id,
            status_code=503,
            upstream_status=response.status_code,
        )
    if response.status_code in {400, 404, 409, 413, 415, 422}:
        return TKPClientError(
            code="TKP_REQUEST_REJECTED",
            public_message="Knowledge ingestion rejected the request",
            correlation_id=correlation_id,
            status_code=response.status_code,
            upstream_status=response.status_code,
        )
    retryable = response.status_code in TKPClient._RETRYABLE_STATUSES
    return TKPClientError(
        code="TKP_UNAVAILABLE" if retryable else "TKP_UPSTREAM_ERROR",
        public_message="Knowledge ingestion is temporarily unavailable",
        correlation_id=correlation_id,
        status_code=503 if retryable else 502,
        upstream_status=response.status_code,
        retryable=retryable,
    )
