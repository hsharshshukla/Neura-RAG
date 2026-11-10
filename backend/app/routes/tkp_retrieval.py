import asyncio
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.deps.workspace import WorkspaceAccess, require_tkp_workspace_access
from app.integrations.tkp.client import TKPClient, TKPClientError
from app.integrations.tkp.schemas import (
    BrowserRetrievalRequest,
    TKPRetrievalRequest,
    TKPRetrievalResponse,
)
from app.rate_limit import limiter

logger = logging.getLogger("neura.tkp_bridge")
router = APIRouter(prefix="/api/v1/tkp", tags=["tkp-retrieval"])


def _correlation_id(request: Request) -> UUID:
    value = getattr(request.state, "correlation_id", None)
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        correlation_id = uuid4()
        request.state.correlation_id = str(correlation_id)
        return correlation_id


def _client(request: Request) -> TKPClient:
    client = getattr(request.app.state, "tkp_client", None)
    if not isinstance(client, TKPClient):
        correlation_id = _correlation_id(request)
        raise TKPClientError(
            code="TKP_NOT_CONFIGURED",
            public_message="Knowledge retrieval is not configured",
            correlation_id=correlation_id,
            status_code=503,
        )
    return client


@router.post(
    "/retrieval/search",
    response_model=TKPRetrievalResponse,
    responses={403: {}, 429: {}, 502: {}, 503: {}, 504: {}},
)
@limiter.limit("20/minute;300/hour")
async def search(
    request: Request,
    response: Response,
    payload: BrowserRetrievalRequest = Body(...),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
) -> TKPRetrievalResponse | JSONResponse:
    """Retrieve only approved TKP projections for the configured staging workspace."""

    correlation_id = _correlation_id(request)
    try:
        retrieval = await _client(request).search(
            TKPRetrievalRequest.from_browser(payload), correlation_id
        )
    except asyncio.CancelledError:
        raise
    except TKPClientError as exc:
        logger.warning(
            "tkp_retrieval_failed",
            extra={
                "code": exc.code,
                "correlation_id": str(exc.correlation_id),
                "upstream_status": exc.upstream_status,
                "user_id": access.user.id,
                "workspace_id": str(access.workspace_id),
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.public_message,
                "correlation_id": str(exc.correlation_id),
                "details": None,
            },
            headers={"X-Correlation-ID": str(exc.correlation_id)},
        )

    logger.info(
        "tkp_retrieval_succeeded",
        extra={
            "correlation_id": str(retrieval.correlation_id),
            "user_id": access.user.id,
            "workspace_id": str(access.workspace_id),
            "result_count": len(retrieval.results),
            "degraded": any(status.degraded for status in retrieval.backend_status),
        },
    )
    return retrieval
