# app/routes/health.py
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health_check():
    """
    Simple healthcheck endpoint.
    Returns status and current server time.
    """
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


@router.get("/health/ready")
async def readiness(request: Request, db: Session = Depends(get_session)):
    checks = {"database": False, "tkp": False}
    try:
        db.exec(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass

    client = getattr(request.app.state, "tkp_client", None)
    if client is not None:
        try:
            correlation_id = UUID(str(getattr(request.state, "correlation_id", "")))
        except ValueError:
            correlation_id = uuid4()
        checks["tkp"] = await client.ready(correlation_id)

    if all(checks.values()):
        return {"status": "ready", "checks": checks}
    return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
