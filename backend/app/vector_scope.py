from typing import Dict, Any, Optional

def build_retrieval_filters(
    tier: str,
    user_email: str,
    session_id: Optional[str]
) -> Dict[str, Any]:
    """
    Free/Mini+: session-scoped search
    Pro: global search (user-wide)
    """
    if tier in {"free", "mini"}:
        # session-only search
        return {"user_email": user_email, "session_id": session_id}
    # Pro: user-wide (no session restriction)
    return {"user_email": user_email}
