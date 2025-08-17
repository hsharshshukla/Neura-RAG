# app/config.py
import os

# ===== Storage (existing) =====
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
DOC_STORAGE_PATH = os.getenv("DOC_STORAGE_PATH", "./uploads")

S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "false").lower() == "true"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# ===== Plans & Models (NEW) =====
FREE_DAILY_CHATS = int(os.getenv("FREE_DAILY_CHATS", "20"))
MINI_DAILY_CHATS = int(os.getenv("MINI_DAILY_CHATS", "-1"))   # -1 => unlimited
PRO_DAILY_CHATS  = int(os.getenv("PRO_DAILY_CHATS", "-1"))

MODEL_FREE = os.getenv("MODEL_FREE", "gpt-4o-mini")
MODEL_MINI = os.getenv("MODEL_MINI", "gpt-4o-mini")
MODEL_PRO  = os.getenv("MODEL_PRO",  "gpt-4o")

def plan_limit(tier: str) -> int:
    tier = (tier or "").lower()
    if tier == "free": return FREE_DAILY_CHATS
    if tier == "mini": return MINI_DAILY_CHATS
    if tier == "pro":  return PRO_DAILY_CHATS
    return 0

def plan_model(tier: str) -> str:
    tier = (tier or "").lower()
    if tier == "free": return MODEL_FREE
    if tier == "mini": return MODEL_MINI
    if tier == "pro":  return MODEL_PRO
    return MODEL_FREE

def is_session_scoped(tier: str) -> bool:
    """Free & Mini+ are session-only; Pro is global."""
    return (tier or "").lower() in {"free", "mini"}
