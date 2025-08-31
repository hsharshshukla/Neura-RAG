# app/rate_limit.py
from __future__ import annotations
import os
from typing import Iterable
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

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
    """
    Best-effort real client IP from common proxy/CDN headers.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    for h in ("cf-connecting-ip", "x-real-ip"):
        v = request.headers.get(h)
        if v:
            return v.strip()
    return request.client.host if request.client else "unknown"

def key_user_or_ip(request: Request) -> str:
    """
    Prefer bearer token (user) else IP.
    Keeps keys stable across NAT/shared IPs for logged-in users.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return ("u:" + auth.split(None, 1)[1][:64])
    return "ip:" + client_ip(request)

# Export a process-wide Limiter
limiter = Limiter(
    key_func=key_user_or_ip,           # per user if authed, else IP
    storage_uri=storage_uri(),
    headers_enabled=True,
    in_memory_fallback_enabled=True,
)

# Convenience: parse RL_* env strings like "20/minute; 200/hour"
def env_limits(name: str, default_value: str | None) -> list[str]:
    return _as_limits(os.getenv(name, default_value))
