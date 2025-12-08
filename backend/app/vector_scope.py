# app/vector_scope.py
from __future__ import annotations

from typing import Dict, Any, Optional


def build_retrieval_filters(
    tier: str,
    user_email: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Base (personal): session-scoped search => include session_id when present
    Pro  (discovery): user-wide search      => no session restriction

    Always include user identifiers when provided.
    """
    t = (tier or "base").strip().lower()

    out: Dict[str, Any] = {}
    if user_email:
        out["user_email"] = user_email
    if user_id is not None:
        out["user_id"] = str(user_id)

    if t in {"base", "free"}:
        # Only constrain by session if we have one
        if session_id is not None:
            out["session_id"] = str(session_id)
    # Pro: no session_id constraint unless the caller forces it elsewhere
    return out


def apply_scope(
    scope: Optional[Dict[str, Any]] = None,
    *,
    tier: Optional[str] = None,
    user_email: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Flexible adapter used by retrieval.py.

    Back-compat:
      retrieval.py calls `apply_scope(scope)` with a dict — this signature
      keeps `scope` as the first positional parameter.

    Inputs considered (left to right precedence):
      - explicit kwargs (tier, user_email, user_id, session_id)
      - values inside `scope` dict: tier, user_email, user_id, session_id/chat_id,
        session_scoped_only (bool)

    Returns a flat dict of filters suitable for vector backends.
    """
    scope = scope or {}

    # Resolve effective values
    eff_tier = (tier or scope.get("tier") or "base")
    # IMPORTANT: don't assume these exist in `scope`
    eff_email = (user_email or scope.get("user_email") or None)
    eff_user_id = (user_id if user_id is not None else scope.get("user_id"))
    eff_sid = session_id or scope.get("session_id") or scope.get("chat_id")
    eff_sid = str(eff_sid) if eff_sid is not None else None

    # If the caller explicitly forces session scoping, treat as base for this query
    if scope.get("session_scoped_only") is True and eff_sid:
        eff_tier = "base"

    # Build filters (only include identifiers that are provided)
    return build_retrieval_filters(
        tier=str(eff_tier),
        user_email=eff_email,
        session_id=eff_sid,
        user_id=eff_user_id,
    )


# Back-compat alias (if older code imports a different helper)
filters_for = apply_scope

__all__ = ["build_retrieval_filters", "apply_scope", "filters_for"]
