# app/utils/openai_helpers.py
from typing import Any, Dict

def usage_to_dict(usage: Any) -> Dict[str, int]:
    """
    Normalize OpenAI SDK v1 usage object (or dict) into a plain dict.
    Safe for None, dict, and Pydantic (v1/v2) models.
    """
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
    # Pydantic v2
    if hasattr(usage, "model_dump") and callable(usage.model_dump):
        d = usage.model_dump()
        return {
            "prompt_tokens": d.get("prompt_tokens"),
            "completion_tokens": d.get("completion_tokens"),
            "total_tokens": d.get("total_tokens"),
        }
    # Pydantic v1
    if hasattr(usage, "dict") and callable(usage.dict):
        d = usage.dict()
        return {
            "prompt_tokens": d.get("prompt_tokens"),
            "completion_tokens": d.get("completion_tokens"),
            "total_tokens": d.get("total_tokens"),
        }
    # Attribute access fallback
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
