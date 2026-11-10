# app/rate_limit.py
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable

from fastapi import Request
from slowapi import Limiter

# from slowapi import Limiter
# from slowapi.util import get_remote_address


def _as_limits(s: str | Iterable[str] | None) -> list[str]:
    if not s:
        return []
    if isinstance(s, str):
        return [chunk.strip() for chunk in s.split(";") if chunk.strip()]
    return [str(x).strip() for x in s if str(x).strip()]


def storage_uri() -> str:
    """
    Use Redis in prod, memory in dev/test.
    Accepts: redis://[:password]@host:port/0  or memory://
    """
    return os.getenv("REDIS_URL", os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")).strip()


def client_ip(request: Request) -> str:
    """Return the trusted direct peer unless proxy headers are explicitly enabled."""
    trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            ip = xff.split(",")[0].strip()
            if ip:
                return ip
        for header in ("cf-connecting-ip", "x-real-ip"):
            value = request.headers.get(header)
            if value:
                return value.strip()
    return request.client.host if request.client else "unknown"


def key_user_or_ip(request: Request) -> str:
    """
    Prefer bearer token (user) else IP.
    Keeps keys stable across NAT/shared IPs for logged-in users.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
    elif request.cookies.get("access_token"):
        token = request.cookies["access_token"]
    if token:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return "credential:" + digest[:24]
    return "ip:" + client_ip(request)


limiter = Limiter(
    key_func=key_user_or_ip,
    storage_uri=storage_uri(),
    headers_enabled=True,
    in_memory_fallback_enabled=os.getenv("APP_ENV", "dev").lower() in {"dev", "test"},
)


# Convenience: parse RL_* env strings like "20/minute; 200/hour"
def env_limits(name: str, default_value: str | None) -> list[str]:
    return _as_limits(os.getenv(name, default_value))
