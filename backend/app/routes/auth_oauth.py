# app/routes/auth_oauth.py
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from datetime import datetime, timedelta
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
import os, json, time

from app.db import get_session
from app.models import User
from app.utils.logger import log_event
from app.routes.auth import create_access_token, set_auth_cookie

# 🔒 SlowAPI per-endpoint limiter
# from app.rate_limit import limiter  # (key_func default = client IP is fine for OAuth)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")
# Read env once
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")

APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY_PATH = os.getenv("APPLE_PRIVATE_KEY_PATH", "")
APPLE_REDIRECT_URI = os.getenv("APPLE_REDIRECT_URI", "")

config = Config(environ={
    "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
    "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
    "APPLE_CLIENT_ID": APPLE_CLIENT_ID,
})
oauth = OAuth(config)

oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
)

oauth.register(
    name="apple",
    api_base_url="https://appleid.apple.com",
    authorize_url="https://appleid.apple.com/auth/authorize",
    access_token_url="https://appleid.apple.com/auth/token",
    client_kwargs={"scope": "name email", "token_endpoint_auth_method": "client_secret_post"},
    client_id=APPLE_CLIENT_ID,
)

def _apple_client_secret() -> str:
    from jose import jwt as jose_jwt
    if not (APPLE_TEAM_ID and APPLE_KEY_ID and APPLE_CLIENT_ID and APPLE_PRIVATE_KEY_PATH):
        raise HTTPException(500, detail="Apple SSO not configured (TEAM_ID/KEY_ID/CLIENT_ID/PRIVATE_KEY_PATH).")
    try:
        with open(APPLE_PRIVATE_KEY_PATH, "r") as f:
            private_key = f.read()
    except FileNotFoundError:
        raise HTTPException(500, detail=f"Apple private key not found at {APPLE_PRIVATE_KEY_PATH}")
    now = int(time.time())
    claims = {
        "iss": APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 1800,
        "aud": "https://appleid.apple.com",
        "sub": APPLE_CLIENT_ID,
    }
    headers = {"kid": APPLE_KEY_ID, "alg": "ES256"}
    return jose_jwt.encode(claims, private_key, algorithm="ES256", headers=headers)

def _upsert_user(db: Session, *, email: str, name: str, provider: str, provider_id: str) -> User:
    u = db.exec(select(User).where(User.provider == provider, User.provider_id == provider_id)).first()
    if u:
        if email and u.email != email: u.email = email
        if name and u.name != name: u.name = name
        db.add(u); db.commit(); db.refresh(u)
        return u
    if email:
        u = db.exec(select(User).where(User.email == email)).first()
        if u:
            u.provider = provider
            u.provider_id = provider_id
            if name and not u.name: u.name = name
            db.add(u); db.commit(); db.refresh(u)
            return u
    u = User(
        email=email or f"{provider_id}@{provider}.sso",
        password=None,
        tier="free",
        name=name or "",
        provider=provider,
        provider_id=provider_id,
        created_at=datetime.utcnow(),
    )
    db.add(u); db.commit(); db.refresh(u)
    return u

# ---------- Google ----------
@router.get("/google/start")
# @limiter.limit("12/minute; 120/hour")  # protect provider initiation
async def google_start(request: Request):
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI):
        # Surface a readable error instead of a 500
        missing = [k for k, v in {
            "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
            "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
            "GOOGLE_REDIRECT_URI": GOOGLE_REDIRECT_URI,
        }.items() if not v]
        raise HTTPException(500, detail=f"Google SSO not configured. Missing: {', '.join(missing)}")
    try:
        return await oauth.google.authorize_redirect(request, GOOGLE_REDIRECT_URI)
    except Exception as e:
        # Helpful trace in logs
        print("google_start error:", repr(e))
        raise

@router.get("/google/callback")
# @limiter.limit("60/minute")  # modest cap; provider redirects user-agents here
async def google_callback(request: Request, db: Session = Depends(get_session)):
    token = await oauth.google.authorize_access_token(request)
    id_token = token.get("id_token")
    if not id_token:
        raise HTTPException(400, "Missing id_token from Google")
    claims = oauth.google.parse_id_token(request, id_token)
    email = claims.get("email")
    sub = claims.get("sub")
    name = claims.get("name") or f"GoogleUser-{sub[:6]}"
    user = _upsert_user(db, email=email, name=name, provider="google", provider_id=sub)
    app_jwt = create_access_token(user)
    log_event("oauth_login", {"provider": "google", "user": email or sub})
    response = RedirectResponse(url=f"{FRONTEND_URL}/oauth/callback")
    set_auth_cookie(response, app_jwt)
    return response

# ---------- Apple ----------
@router.get("/apple/start")
# @limiter.limit("12/minute; 120/hour")
async def apple_start(request: Request):
    if not (APPLE_CLIENT_ID and APPLE_REDIRECT_URI):
        missing = [k for k, v in {
            "APPLE_CLIENT_ID": APPLE_CLIENT_ID,
            "APPLE_REDIRECT_URI": APPLE_REDIRECT_URI,
        }.items() if not v]
        raise HTTPException(500, detail=f"Apple SSO not configured. Missing: {', '.join(missing)}")
    oauth.apple.client_secret = _apple_client_secret()
    return await oauth.apple.authorize_redirect(
        request,
        APPLE_REDIRECT_URI,
        response_mode="form_post",
        response_type="code",
    )

@router.post("/apple/callback")
@router.get("/apple/callback")
# @limiter.limit("60/minute")  # GET/POST callback
async def apple_callback(request: Request, db: Session = Depends(get_session)):
    oauth.apple.client_secret = _apple_client_secret()
    token = await oauth.apple.authorize_access_token(request)
    id_token = token.get("id_token")
    if not id_token:
        raise HTTPException(400, "Missing id_token from Apple")
    claims = oauth.apple.parse_id_token(request, id_token)
    email = claims.get("email")
    sub = claims.get("sub")
    name = ""
    user = _upsert_user(db, email=email, name=name, provider="apple", provider_id=sub)
    app_jwt = create_access_token(user)
    log_event("oauth_login", {"provider": "apple", "user": email or sub})
    response = RedirectResponse(url=f"{FRONTEND_URL}/oauth/callback")
    set_auth_cookie(response, app_jwt)
    return response
