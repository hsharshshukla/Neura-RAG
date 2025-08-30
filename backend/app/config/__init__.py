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

# ----- Plans & Models (env only; logic lives below) -----
# Daily chat limits (-1 => unlimited)
FREE_DAILY_CHATS = int(os.getenv("FREE_DAILY_CHATS", "20"))
MINI_DAILY_CHATS = int(os.getenv("MINI_DAILY_CHATS", "-1"))
PRO_DAILY_CHATS  = int(os.getenv("PRO_DAILY_CHATS", "-1"))

# Model names per tier
MODEL_FREE = os.getenv("MODEL_FREE", "gpt-4o-mini")
MODEL_MINI = os.getenv("MODEL_MINI", "gpt-4o-mini")
MODEL_PRO  = os.getenv("MODEL_PRO",  "gpt-4o")

# Monthly token caps (optional; used by plan_policy)
PLAN_FREE_MONTHLY_TOKEN_LIMIT = int(os.getenv("PLAN_FREE_MONTHLY_TOKEN_LIMIT", "200000"))
PLAN_MINI_MONTHLY_TOKEN_LIMIT = int(os.getenv("PLAN_MINI_MONTHLY_TOKEN_LIMIT", "500000"))
PLAN_PRO_MONTHLY_TOKEN_LIMIT  = int(os.getenv("PLAN_PRO_MONTHLY_TOKEN_LIMIT", "1000000"))

# =======================================================
# Plan policy logic (lives in a separate module, re-exported)
# =======================================================
from .plan_policy import (
    PLAN_FREE, PLAN_MINI, PLAN_PRO,
    plan_limit, plan_model, is_session_scoped,
    get_or_create_usage, check_and_increment_chat_quota,
    monthly_token_limit_for, monthly_tokens_used, monthly_usage_percent,
)
