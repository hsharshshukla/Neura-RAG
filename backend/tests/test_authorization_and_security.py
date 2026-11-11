from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import SecretStr, ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config.security import SecuritySettings, get_security_settings
from app.db import get_session
from app.deps.auth import get_current_user
from app.deps.chat_session import require_owned_chat_session
from app.deps.workspace import require_tkp_workspace_access
from app.integrations.tkp.client import TKPClient
from app.integrations.tkp.config import TKPSettings, get_tkp_settings
from app.middleware.security import CSRFMiddleware
from app.models import ChatSession, User, Workspace, WorkspaceMembership
from app.rate_limit import client_ip, limiter
from app.routes import auth as auth_routes
from app.routes.chat import ask
from app.routes.search import global_search
from app.routes.tkp_retrieval import router as tkp_router
from app.routes.upload import check_duplicate
from tests.test_tkp_client import _response


def _database() -> tuple[object, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine, Session(engine)


def test_rate_limit_ip_ignores_untrusted_forwarded_headers(monkeypatch) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"198.51.100.9")],
            "query_string": b"",
            "client": ("203.0.113.7", 1234),
            "server": ("test", 80),
            "scheme": "http",
        }
    )
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    assert client_ip(request) == "203.0.113.7"


def test_workspace_membership_is_required_and_fixed() -> None:
    _, db = _database()
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    now = datetime.now(UTC)
    user = User(email="reader@example.test", password="hash", created_at=now)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Workspace(id=str(workspace_id), name="staging", active=True, created_at=now))
    db.add(Workspace(id=str(other_workspace_id), name="other", active=True, created_at=now))
    db.add(
        WorkspaceMembership(
            workspace_id=str(other_workspace_id),
            user_id=user.id,
            role="reader",
            created_at=now,
        )
    )
    db.commit()
    settings = TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        staging_workspace_id=workspace_id,
        environment="test",
    )

    with pytest.raises(HTTPException) as denied:
        require_tkp_workspace_access(user=user, db=db, settings=settings)
    assert denied.value.status_code == 403

    db.add(
        WorkspaceMembership(
            workspace_id=str(workspace_id),
            user_id=user.id,
            role="reader",
            created_at=now,
        )
    )
    db.commit()
    access = require_tkp_workspace_access(user=user, db=db, settings=settings)
    assert access.workspace_id == workspace_id

    membership = db.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == str(workspace_id),
            WorkspaceMembership.user_id == user.id,
        )
    ).one()
    membership.active = False
    db.add(membership)
    db.commit()
    with pytest.raises(HTTPException) as inactive_membership:
        require_tkp_workspace_access(user=user, db=db, settings=settings)
    assert inactive_membership.value.status_code == 403

    membership.active = True
    workspace = db.get(Workspace, str(workspace_id))
    assert workspace is not None
    workspace.active = False
    db.add(membership)
    db.add(workspace)
    db.commit()
    with pytest.raises(HTTPException) as inactive_workspace:
        require_tkp_workspace_access(user=user, db=db, settings=settings)
    assert inactive_workspace.value.status_code == 403


def test_forged_jwt_trust_claims_and_stale_versions_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_security_settings.cache_clear()
    engine, db = _database()
    now = datetime.now(UTC)
    user = User(email="trust@example.test", password="hash", token_version=4, created_at=now)
    db.add(user)
    db.commit()
    settings = get_security_settings()

    def encoded(**overrides) -> str:
        claims = {
            "sub": user.email,
            "ver": user.token_version,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_alg,
        )

    for token in (
        encoded(iss="forged-issuer"),
        encoded(aud="forged-audience"),
        encoded(ver=user.token_version - 1),
    ):
        with pytest.raises(HTTPException) as rejected:
            get_current_user(authorization=f"Bearer {token}", access_cookie=None, db=db)
        assert rejected.value.status_code == 401

    assert (
        get_current_user(
            authorization=f"Bearer {encoded()}",
            access_cookie=None,
            db=db,
        )
        == user.email
    )
    db.close()
    engine.dispose()


def test_foreign_chat_session_is_indistinguishable_from_missing() -> None:
    _, db = _database()
    now = datetime.now(UTC)
    owner = User(email="owner@example.test", password="hash", created_at=now)
    attacker = User(email="attacker@example.test", password="hash", created_at=now)
    db.add(owner)
    db.add(attacker)
    db.commit()
    db.refresh(owner)
    db.refresh(attacker)
    chat = ChatSession(user_id=owner.id, title="private", created_at=now)
    db.add(chat)
    db.commit()
    db.refresh(chat)

    with pytest.raises(HTTPException) as foreign:
        require_owned_chat_session(db, session_id=chat.id, user_id=attacker.id)
    with pytest.raises(HTTPException) as missing:
        require_owned_chat_session(db, session_id=999_999, user_id=attacker.id)
    assert (foreign.value.status_code, foreign.value.detail) == (
        missing.value.status_code,
        missing.value.detail,
    )


def test_csrf_required_for_cookie_authenticated_mutation(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_security_settings.cache_clear()
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/mutate")
    async def mutate(request: Request):
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("access_token", "session")
    assert client.post("/mutate").status_code == 403
    client.cookies.set("csrf_token", "csrf-value")
    assert client.post("/mutate", headers={"X-CSRF-Token": "csrf-value"}).status_code == 200
    client.cookies.set("csrf_token", "wrong-value")
    assert (
        client.post("/mutate", headers={"Authorization": "Bearer service-token"}).status_code == 200
    )


def test_auth_cookie_flags_are_secure(monkeypatch) -> None:
    monkeypatch.setattr(auth_routes, "COOKIE_SECURE", True)
    monkeypatch.setattr(auth_routes, "COOKIE_SAMESITE", "strict")
    response = Response()
    auth_routes.set_auth_cookie(response, "signed-token")
    cookies = response.headers.getlist("set-cookie")
    access = next(value for value in cookies if value.startswith("access_token="))
    csrf = next(value for value in cookies if value.startswith("csrf_token="))
    assert "HttpOnly" in access
    assert "Secure" in access
    assert "SameSite=strict" in access
    assert "HttpOnly" not in csrf
    assert "Secure" in csrf
    assert "SameSite=strict" in csrf


def test_insecure_or_default_secrets_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SecuritySettings(jwt_secret=SecretStr("supersecretkey"))
    with pytest.raises(ValidationError):
        SecuritySettings(jwt_secret=SecretStr("replace-with-at-least-32-random-characters"))
    with pytest.raises(ValidationError):
        SecuritySettings(jwt_secret=SecretStr(" " * 32))
    with pytest.raises(ValidationError):
        TKPSettings(
            internal_url="http://tkp.test",
            service_token=SecretStr("replace-with-the-read-only-tkp-service-token"),
            staging_workspace_id=uuid4(),
        )
    with pytest.raises(ValidationError):
        SecuritySettings(
            app_env="staging",
            jwt_secret=SecretStr("unique-secret-with-at-least-thirty-two-bytes"),
            cookie_secure=False,
        )


def test_tkp_route_requires_authentication_and_preserves_lineage(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_security_settings.cache_clear()
    engine, db = _database()
    workspace_id = uuid4()
    now = datetime.now(UTC)
    user = User(email="reader@example.test", password="hash", token_version=0, created_at=now)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Workspace(id=str(workspace_id), name="staging", active=True, created_at=now))
    db.add(
        WorkspaceMembership(
            workspace_id=str(workspace_id),
            user_id=user.id,
            role="reader",
            created_at=now,
        )
    )
    db.commit()
    tkp_settings = TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        staging_workspace_id=workspace_id,
        environment="test",
        max_attempts=1,
    )

    async def upstream(request: httpx.Request) -> httpx.Response:
        correlation_id = request.headers["X-Correlation-ID"]
        return httpx.Response(200, json=_response(UUID(correlation_id)))

    bridge = TKPClient(tkp_settings, transport=httpx.MockTransport(upstream))
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(tkp_router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_tkp_settings] = lambda: tkp_settings

    client = TestClient(app)
    assert (
        client.post("/api/v1/tkp/retrieval/search", json={"query": "approved fix"}).status_code
        == 401
    )

    security = get_security_settings()
    token = jwt.encode(
        {
            "sub": user.email,
            "ver": user.token_version,
            "iss": security.jwt_issuer,
            "aud": security.jwt_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        security.jwt_secret.get_secret_value(),
        algorithm=security.jwt_alg,
    )
    response = client.post(
        "/api/v1/tkp/retrieval/search",
        json={"query": "approved fix"},
        headers={"Authorization": f"Bearer {token}"},
    )
    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()

    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["projection_id"]
    assert result["article_id"]
    assert result["revision_id"]
    assert result["claim_references"][0]["candidate_claim_id"]
    assert result["claim_references"][0]["source_fragment_ids"]


def test_browser_cannot_override_workspace_and_route_is_rate_limited(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_security_settings.cache_clear()
    engine, db = _database()
    workspace_id = uuid4()
    now = datetime.now(UTC)
    user = User(email=f"reader-{uuid4()}@example.test", password="hash", created_at=now)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Workspace(id=str(workspace_id), name="staging", active=True, created_at=now))
    db.add(WorkspaceMembership(workspace_id=str(workspace_id), user_id=user.id, role="reader"))
    db.commit()
    settings = TKPSettings(
        internal_url="https://tkp.internal",
        service_token=SecretStr("read-only-test-token-123456789"),
        staging_workspace_id=workspace_id,
        environment="test",
        max_attempts=1,
    )

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(UUID(request.headers["X-Correlation-ID"])))

    bridge = TKPClient(settings, transport=httpx.MockTransport(upstream))
    app = FastAPI()
    app.state.limiter = limiter
    app.state.tkp_client = bridge
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(tkp_router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_tkp_settings] = lambda: settings
    security = get_security_settings()
    token = jwt.encode(
        {
            "sub": user.email,
            "ver": 0,
            "iss": security.jwt_issuer,
            "aud": security.jwt_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        security.jwt_secret.get_secret_value(),
        algorithm=security.jwt_alg,
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    forged = client.post(
        "/api/v1/tkp/retrieval/search",
        json={"query": "approved fix", "workspace_id": str(uuid4())},
        headers=headers,
    )
    assert forged.status_code == 422
    for _ in range(20):
        assert (
            client.post(
                "/api/v1/tkp/retrieval/search",
                json={"query": "approved fix"},
                headers=headers,
            ).status_code
            == 200
        )
    limited = client.post(
        "/api/v1/tkp/retrieval/search",
        json={"query": "approved fix"},
        headers=headers,
    )
    asyncio.run(bridge.aclose())
    db.close()
    engine.dispose()
    assert limited.status_code == 429


def test_tkp_mode_disables_all_legacy_organizational_rag(monkeypatch) -> None:
    monkeypatch.setenv("ORGANIZATIONAL_RAG_MODE", "tkp")
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/chat",
        "raw_path": b"/api/v1/chat",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 443),
    }
    request = Request(scope)
    with pytest.raises(HTTPException) as chat_denied:
        asyncio.run(inspect.unwrap(ask)(request=request, db=None, user_email="reader@example.test"))
    with pytest.raises(HTTPException) as search_denied:
        global_search(
            request=request,
            response=Response(),
            q="approved fix",
            current_user="reader@example.test",
            db=None,
        )
    with pytest.raises(HTTPException) as upload_denied:
        check_duplicate(
            request=request,
            response=Response(),
            sha256="hash",
            size=1,
            session_id=1,
            db=None,
            user_email="reader@example.test",
        )
    assert {
        chat_denied.value.status_code,
        search_denied.value.status_code,
        upload_denied.value.status_code,
    } == {409}
