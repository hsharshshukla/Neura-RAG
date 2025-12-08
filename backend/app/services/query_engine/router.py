from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional
from app.deps.auth import get_current_user
from app.config.plan_policy import plan_for
from .pipeline_base import answer_query_base
from .pipeline_pro import answer_query_pro

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    query: str
    scope: Optional[Dict[str, Any]] = None

@router.post("")
async def chat(req: ChatRequest, user=Depends(get_current_user)):
    if not req.query or not req.query.strip():
        raise HTTPException(400, "Empty query")
    scope = req.scope or {}

    plan = plan_for(user)  # "base" | "pro"
    if plan == "pro":
        return await answer_query_pro(user.id, req.query, scope)
    scope["session_scoped_only"] = True
    return await answer_query_base(user.id, req.query, scope)
