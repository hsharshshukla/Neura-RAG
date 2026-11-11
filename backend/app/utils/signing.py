# backend/app/utils/signing.py
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _secret() -> bytes:
    value = os.getenv("CHECKOUT_SIGNING_SECRET", "")
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("CHECKOUT_SIGNING_SECRET must contain at least 32 bytes")
    return value.encode("utf-8")


def sign_payload(data: dict[str, Any], ttl_seconds: int = 900) -> dict[str, Any]:
    payload = {**data, "exp": int(time.time()) + ttl_seconds}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()
    return {"payload": payload, "signature": base64.urlsafe_b64encode(sig).decode()}


def verify_signature(payload: dict[str, Any], signature: str) -> bool:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    expected = hmac.new(_secret(), body, hashlib.sha256).digest()
    try:
        given = base64.urlsafe_b64decode(signature.encode())
    except (ValueError, binascii.Error):
        return False
    if not hmac.compare_digest(expected, given):
        return False
    expires_at = payload.get("exp")
    return isinstance(expires_at, int | float) and expires_at >= int(time.time())
