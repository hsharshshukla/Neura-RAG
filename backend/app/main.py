# app/main.py
from __future__ import annotations

import os
import logging
import inspect
from typing import Iterable, Optional, Set

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

# Centralized rate limit objects/helpers
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.rate_limit import limiter  # uses user-or-IP keying and Redis/memory storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("neura.main")

app = FastAPI(title="Neura API")

# ============================================================
# CORS (keep localhost & vite ports)
# ============================================================
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # Add production domain(s) if you want CORS for them as well
    os.getenv("FRONTEND_URL", "").strip() or "https://www.neurokron.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in ALLOWED_ORIGINS if o],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|([\w-]+\.)*neurokron\.com)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Rate limiting (SlowAPI)
#   - Storage configured in app.rate_limit (REDIS_URL or memory://)
#   - We attach per-router rules below (no global default)
# ============================================================
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# JSON 429 (nicer than the default HTML)
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    reset_in = None
    if isinstance(exc.detail, dict):
        reset_in = exc.detail.get("reset_in")
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limited",
            "message": "Too many requests. Please slow down.",
            "retry_after_seconds": reset_in,
        },
    )

def _as_limits(s: str | Iterable[str] | None) -> list[str]:
    if not s:
        return []
    if isinstance(s, str):
        # allow "20/minute; 200/hour" style
        return [chunk.strip() for chunk in s.split(";") if chunk.strip()]
    return [str(x).strip() for x in s if str(x).strip()]

def _callable_has_req_param(fn) -> bool:
    """
    SlowAPI's decorator requires the endpoint to accept a `request` or `websocket` param.
    Inspect the *original* function (unwrap decorators) and verify presence.
    """
    # Unwrap functools.wraps, FastAPI wrappers, etc.
    seen = set()
    while hasattr(fn, "__wrapped__") and fn not in seen:
        seen.add(fn)
        fn = fn.__wrapped__  # type: ignore[attr-defined]

    try:
        params = inspect.signature(fn).parameters
        return ("request" in params) or ("websocket" in params)
    except (TypeError, ValueError):
        # Builtins/callables without inspectable signature: play it safe and skip
        return False

def _limit_router(
    router,
    limits: str | Iterable[str],
    methods: Optional[Set[str]] = None,
    path_prefix: Optional[str] = None,
) -> None:
    """
    Wrap each APIRoute.endpoint in `router` with the given SlowAPI limits.
    - methods: if provided, only routes matching any of these HTTP methods are wrapped.
    - path_prefix: if provided, only paths starting with this prefix are wrapped.
    Skips endpoints that do not accept a `request`/`websocket` parameter.
    """
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

        # Only decorate if endpoint signature is compatible with SlowAPI
        if not _callable_has_req_param(route.endpoint):
            log.warning(
                "Skipping RL for %s %s (no 'request' or 'websocket' argument).",
                ",".join(route.methods),
                route.path,
            )
            continue

        wrapped = route.endpoint
        for rule in rules:
            wrapped = limiter.limit(rule)(wrapped)
        route.endpoint = wrapped
        log.info(
            "Rate limit attached: %s %s -> %s",
            ",".join(route.methods),
            route.path,
            "; ".join(rules),
        )

# ============================================================
# Attach per-router limits (tweak via env; examples below)
#   RL_* values accept one or multiple rules, separated by ';'
#   e.g. RL_CHAT="20/minute; 200/hour"
# ============================================================
APP_ENV = os.getenv("APP_ENV", "dev").lower()

RL_CHAT   = os.getenv("RL_CHAT",   "30/minute; 600/hour")   # chat completions
RL_UPLOAD = os.getenv("RL_UPLOAD", "10/minute; 100/hour")   # file uploads
RL_AUTH   = os.getenv("RL_AUTH",   "20/minute")             # login/register/etc
RL_FORGOT = os.getenv("RL_FORGOT", "3/minute; 50/hour")     # forgot password
RL_SEARCH = os.getenv("RL_SEARCH", "60/minute; 1000/hour")  # search endpoints
RL_BILL   = os.getenv("RL_BILL",   "10/minute; 100/hour")   # checkout/cancel

# In production you might want to be a bit tighter by default
if APP_ENV == "prod":
    RL_CHAT   = os.getenv("RL_CHAT",   "20/minute; 300/hour")
    RL_UPLOAD = os.getenv("RL_UPLOAD", "6/minute; 60/hour")
    RL_AUTH   = os.getenv("RL_AUTH",   "12/minute")
    RL_FORGOT = os.getenv("RL_FORGOT", "3/minute; 30/hour")
    RL_SEARCH = os.getenv("RL_SEARCH", "40/minute; 600/hour")
    RL_BILL   = os.getenv("RL_BILL",   "6/minute; 60/hour")

# ============================================================
# Register routers (apply limits BEFORE include_router)
# ============================================================
from app.routes import (
    auth, chat, upload, billing, profile, auth_oauth,
    search, settings as settings_routes, admin, auth_password, health
)

# Hot / expensive endpoints (POSTs only):
_limit_router(chat.router,   RL_CHAT,   methods={"POST"})
_limit_router(upload.router, RL_UPLOAD, methods={"POST"})
_limit_router(auth.router,   RL_AUTH,   methods={"POST"})
_limit_router(auth_password.router, RL_FORGOT, methods={"POST"})
# Search can be GET or POST depending on your impl; here we rate-limit both:
_limit_router(search.router, RL_SEARCH, methods={"GET", "POST"})
_limit_router(billing.router, RL_BILL, methods={"POST"}, path_prefix="/api/v1/billing")

# Now mount all routers
app.include_router(auth.router)        # /api/v1/auth/*
app.include_router(auth.alias)         # /api/v1/me  (soft alias)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(billing.router)     # includes /billing/prices, /billing/guard, etc.
app.include_router(profile.router)
app.include_router(auth_oauth.router)
app.include_router(search.router)
app.include_router(settings_routes.router)
app.include_router(admin.router)
app.include_router(auth_password.router)
app.include_router(health.router)

# Simple root ping (not rate-limited)
@app.get("/health")
def health_root():
    return {"ok": True}
