# app/main.py
from __future__ import annotations

import os
import uuid
import inspect
import logging
from typing import Iterable, Optional, Set

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError

# Lifespan (your existing)
from app.lifespan import lifespan

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.rate_limit import limiter
from app.middleware.security import CSRFMiddleware

# ---- OpenTelemetry ----------------------------------------------------------
from app.telemetry.trace import init_tracer  # you added this module earlier
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
try:
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    _has_psycopg3 = True
except Exception:
    _has_psycopg3 = False
    PsycopgInstrumentor = None  # type: ignore

try:
    from opentelemetry.instrumentation.psycopg import Psycopg2Instrumentor
    _has_psycopg2 = True
except Exception:
    _has_psycopg2 = False
    Psycopg2Instrumentor = None  # type: ignore

try:
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    _has_redis_inst = True
except Exception:
    _has_redis_inst = False
    RedisInstrumentor = None  # type: ignore
# -----------------------------------------------------------------------------

# Routers (your existing)
from app.routes import (
    auth, chat, upload, billing, profile, auth_oauth,
    search, settings as settings_routes,
    admin, auth_password, health, checkout_intent,
    admin_coupons, admin_perf, admin_insights,
    feedback, admin_refresh, admin_summary,
    admin_actives, admin_usage, admin_bulk_upload,
    admin_users_bulk,
    tkp_retrieval,
)
from app.routes.chat_status import router as chat_status_router

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("neura.main")

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            cid = str(uuid.UUID(request.headers.get("x-correlation-id", "")))
        except ValueError:
            cid = str(uuid.uuid4())
        request.state.correlation_id = cid
        response: Response = await call_next(request)
        response.headers["x-correlation-id"] = cid
        return response

def _as_limits(s: str | Iterable[str] | None) -> list[str]:
    if not s:
        return []
    if isinstance(s, str):
        return [chunk.strip() for chunk in s.split(";") if chunk.strip()]
    return [str(x).strip() for x in s if str(x).strip()]

def _callable_has_req_param(fn) -> bool:
    seen = set()
    while hasattr(fn, "__wrapped__") and fn not in seen:
        seen.add(fn)
        fn = fn.__wrapped__  # type: ignore[attr-defined]
    try:
        params = inspect.signature(fn).parameters
        return ("request" in params) or ("websocket" in params)
    except (TypeError, ValueError):
        return False

def _limit_router(
    router,
    limits: str | Iterable[str],
    methods: Optional[Set[str]] = None,
    path_prefix: Optional[str] = None,
) -> None:
    rules = _as_limits(limits)
    if not rules:
        return

    for route in getattr(router, "routes", []):
        if not isinstance(route, APIRoute):
            continue
        if methods and route.methods.isdisjoint({m.upper() for m in methods}):
            continue
        if path_prefix and not route.path.startswith(path_prefix):
            continue

        if not _callable_has_req_param(route.endpoint):
            log.warning(
                "Skipping RL for %s %s (no 'request' or 'websocket' argument).",
                ",".join(route.methods),
                route.path,
            )
            continue

        # wrapped = route.endpoint
        # for rule in rules:
        #     wrapped = limiter.limit(rule)(wrapped)
        # route.endpoint = wrapped
        log.info(
            "Rate limit attached: %s %s -> %s",
            ",".join(route.methods),
            route.path,
            "; ".join(rules),
        )

def _instrument_otel(app: FastAPI) -> None:
    init_tracer()
    FastAPIInstrumentor().instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    if _has_psycopg3 and PsycopgInstrumentor:
        try: PsycopgInstrumentor().instrument()
        except Exception: pass
    elif _has_psycopg2 and Psycopg2Instrumentor:
        try: Psycopg2Instrumentor().instrument()
        except Exception: pass
    if _has_redis_inst and RedisInstrumentor:
        try: RedisInstrumentor().instrument()
        except Exception: pass

APP_ENV = os.getenv("APP_ENV", "dev").lower()

# Rate-limit presets
RL_CHAT   = os.getenv("RL_CHAT",   "30/minute; 600/hour")
RL_UPLOAD = os.getenv("RL_UPLOAD", "10/minute; 100/hour")
RL_AUTH   = os.getenv("RL_AUTH",   "20/minute")
RL_FORGOT = os.getenv("RL_FORGOT", "3/minute; 50/hour")
RL_SEARCH = os.getenv("RL_SEARCH", "60/minute; 1000/hour")
RL_BILL   = os.getenv("RL_BILL",   "10/minute; 100/hour")

if APP_ENV == "prod":
    RL_CHAT   = os.getenv("RL_CHAT",   "20/minute; 300/hour")
    RL_UPLOAD = os.getenv("RL_UPLOAD", "6/minute; 60/hour")
    RL_AUTH   = os.getenv("RL_AUTH",   "12/minute")
    RL_FORGOT = os.getenv("RL_FORGOT", "3/minute; 30/hour")
    RL_SEARCH = os.getenv("RL_SEARCH", "40/minute; 600/hour")
    RL_BILL   = os.getenv("RL_BILL",   "6/minute; 60/hour")

app = FastAPI(title="Neura API", lifespan=lifespan)

default_origins = "http://localhost:3000,http://127.0.0.1:3000"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", default_origins).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "X-Correlation-ID",
        "X-Requested-With",
    ],
)

app.add_middleware(CSRFMiddleware)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if os.getenv("ENABLE_CORRELATION", "true").lower() in ("1", "true", "yes"):
    app.add_middleware(CorrelationIdMiddleware)

_instrument_otel(app)

# @app.exception_handler(RateLimitExceeded)
# async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
#     reset_in = None
#     if isinstance(exc.detail, dict):
#         reset_in = exc.detail.get("reset_in")
#     return JSONResponse(
#         status_code=429,
#         content={
#             "error": "rate_limited",
#             "message": "Too many requests. Please slow down.",
#             "retry_after_seconds": reset_in,
#         },
#     )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    safe_errors = [
        {"type": error.get("type"), "loc": error.get("loc")}
        for error in exc.errors()
    ]
    logger.error(
        "422 Validation error on %s %s; errors=%s; content_type=%s",
        request.method, request.url.path, safe_errors,
        request.headers.get("content-type"),
    )
    return JSONResponse(status_code=422, content={"detail": safe_errors})

# Apply per-router limits BEFORE include_router
# _limit_router(chat.router,   RL_CHAT,   methods={"POST"})
# _limit_router(upload.router, RL_UPLOAD, methods={"POST"})

# Mount routers
app.include_router(auth.router)
app.include_router(auth.alias)         # /api/v1/me
app.include_router(chat.router)
app.include_router(chat_status_router) # /api/v1/chat/{id}/status
app.include_router(upload.router)
app.include_router(billing.router)
app.include_router(profile.router)
app.include_router(auth_oauth.router)
app.include_router(search.router)
app.include_router(settings_routes.router)
app.include_router(admin.router)
app.include_router(auth_password.router)
app.include_router(health.router)
app.include_router(checkout_intent.router)
app.include_router(admin_coupons.router)
app.include_router(admin_perf.router)
app.include_router(admin_insights.router)
app.include_router(feedback.router)
app.include_router(admin_refresh.router)
app.include_router(admin_summary.router)
app.include_router(admin_actives.router)
app.include_router(admin_usage.router)
app.include_router(admin_bulk_upload.router)
app.include_router(admin_users_bulk.router)
app.include_router(tkp_retrieval.router)

@app.get("/health")
def health_root():
    return {"ok": True}

