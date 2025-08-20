# app/routes/health.py
from fastapi import APIRouter
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["health"])

@router.get("/health")
def health_check():
    """
    Simple healthcheck endpoint.
    Returns status and current server time.
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
