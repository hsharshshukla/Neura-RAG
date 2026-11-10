from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.integrations.tkp.config import TKPSettings
from app.integrations.tkp.schemas import (
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
