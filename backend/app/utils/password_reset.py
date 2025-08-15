import hashlib, hmac, os
from datetime import datetime
from fastapi import HTTPException, status

def generate_raw_token() -> str:
    return os.urandom(32).hex()

def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def ensure_not_expired(expires_at: datetime):
    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
