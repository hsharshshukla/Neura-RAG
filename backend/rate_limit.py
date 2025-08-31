# app/rate_limit.py
from __future__ import annotations
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

def _storage():
    # redis://:pass@host:6379/0  (recommended in prod)
    return os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")

# Default: fairly high ceiling; override per-route below
_default = os.getenv("RATE_LIMIT_DEFAULT", "300/minute")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_default],
    storage_uri=_storage(),
)

def key_user_or_ip(request):
    # Try to partition by bearer token first; fall back to IP
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1][:64]  # token prefix
    return get_remote_address(request)
