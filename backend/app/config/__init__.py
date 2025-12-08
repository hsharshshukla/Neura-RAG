# app/config/__init__.py
"""
Single source of truth for settings (env) and plan policy helpers.

This file replaces the old module `app/config.py`. Make sure that file is removed,
otherwise Python will see both a package (this directory) and a module with the same name.
"""

from __future__ import annotations
import os

# =========================
# Env settings (moved here)
# =========================

# ----- Storage -----
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
DOC_STORAGE_PATH = os.getenv("DOC_STORAGE_PATH", "./uploads")

S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "false").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# =========================
# Plans & Models (env)
# Two-tier world: BASE / PRO
# Keep legacy envs as fallbacks so nothing breaks.
# =========================

def _geti(default: int, *names: str) -> int:
    for n in names:
        v = os.getenv(n, "").strip()
        if v and (v.lstrip("-").isdigit()):
            try:
                return int(v)
            except Exception:
                pass
    return default

def _gets(default: str, *names: str) -> str:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return default

# Daily chat limits (-1 => unlimited)
BASE_DAILY_CHATS = _geti(20,  "BASE_DAILY_CHATS", "FREE_DAILY_CHATS")
PRO_DAILY_CHATS  = _geti(-1,  "PRO_DAILY_CHATS")

# Model names per tier (prefer OPENAI_MODEL_*; fall back to older names)
OPENAI_MODEL_BASE = _gets("gpt-4.1-mini", "OPENAI_MODEL_BASE", "MODEL_BASE", "MODEL_FREE")
OPENAI_MODEL_PRO  = _gets("gpt-5",        "OPENAI_MODEL_PRO",  "MODEL_PRO")

# Monthly token caps (optional; 0 => treat as unlimited in policy)
PLAN_BASE_MONTHLY_TOKEN_LIMIT = _geti(200_000, "PLAN_BASE_MONTHLY_TOKEN_LIMIT", "PLAN_FREE_MONTHLY_TOKEN_LIMIT")
PLAN_PRO_MONTHLY_TOKEN_LIMIT  = _geti(1_000_000, "PLAN_PRO_MONTHLY_TOKEN_LIMIT")

# =======================================================
# Plan policy logic (lives in a separate module, re-exported)
# =======================================================
from .plan_policy import (
    PLAN_BASE, PLAN_PRO,
    plan_limit, plan_model, is_session_scoped,
    get_or_create_usage, check_and_increment_chat_quota,
    monthly_token_limit_for, monthly_tokens_used, monthly_usage_percent,
    plan_for, caps_for, is_pro_active,
)

# ---- Back-compat aliases so old imports keep working ----
PLAN_FREE = PLAN_BASE
PLAN_MINI = PLAN_BASE
MODEL_FREE = OPENAI_MODEL_BASE
MODEL_MINI = OPENAI_MODEL_BASE
MODEL_PRO  = OPENAI_MODEL_PRO
