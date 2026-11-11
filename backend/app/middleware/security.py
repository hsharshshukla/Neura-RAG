from __future__ import annotations

import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.security import get_security_settings


class CSRFMiddleware:
    """Double-submit protection for state-changing cookie-authenticated requests."""

    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in self._SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        settings = get_security_settings()
        cookie_authenticated = bool(request.cookies.get(settings.access_cookie_name))
        bearer_authenticated = (
            request.headers.get("authorization", "").lower().startswith("bearer ")
        )
        if cookie_authenticated and not bearer_authenticated:
            cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
            header_token = request.headers.get("x-csrf-token", "")
            if not cookie_token or not secrets.compare_digest(cookie_token, header_token):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "code": "CSRF_VALIDATION_FAILED",
                        "message": "Request could not be verified",
                        "correlation_id": str(
                            getattr(request.state, "correlation_id", "unavailable")
                        ),
                        "details": None,
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
