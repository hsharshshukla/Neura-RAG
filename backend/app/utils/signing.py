# backend/app/utils/signing.py
from __future__ import annotations
import hmac, hashlib, base64, json, os, time
from typing import Dict, Any

_SECRET = os.getenv("CHECKOUT_SIGNING_SECRET", "dev-secret-change-me").encode()

def sign_payload(data: Dict[str, Any], ttl_seconds: int = 900) -> Dict[str, Any]:
    payload = {**data, "exp": int(time.time()) + ttl_seconds}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_SECRET, body, hashlib.sha256).digest()
    return {"payload": payload, "signature": base64.urlsafe_b64encode(sig).decode()}

def verify_signature(payload: Dict[str, Any], signature: str) -> bool:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    expected = hmac.new(_SECRET, body, hashlib.sha256).digest()
    try:
        given = base64.urlsafe_b64decode(signature.encode())
    except Exception:
        return False
    if not hmac.compare_digest(expected, given):
        return False
    return payload.get("exp", 0) >= int(time.time())
