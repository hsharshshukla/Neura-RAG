# app/services/query_engine/prompt_config.py
from __future__ import annotations
import os
from dataclasses import dataclass

"""
Single place to read prompts from env with safe defaults.
- Backward compatible: existing code using system_base/system_pro and user_prefix_* keeps working.
- Adds OpenText-specific Pro prompt + prefix overrides via env (optional).
  Env keys:
    PROMPT_SYSTEM_BASE
    PROMPT_SYSTEM_PRO
    PROMPT_USER_PREFIX_BASE
    PROMPT_USER_PREFIX_PRO

    PROMPT_SYSTEM_PRO_OPENTEXT
    PROMPT_USER_PREFIX_PRO_OPENTEXT
"""

@dataclass(frozen=True)
class Prompts:
    # Generic system prompts
    system_base: str
    system_pro: str

    # User prompt wrappers (optional)
    user_prefix_base: str
    user_prefix_pro: str

    # Pro: OpenText specialization (optional)
    system_pro_opentext: str
    user_prefix_pro_opentext: str


def _default_base_system() -> str:
    return (
        "You are a strict RAG assistant for a session-scoped workspace. "
        "Answer ONLY with facts from the provided context. "
        "If the answer is not in the context, say you don't have enough information "
        "and suggest what file/section to provide. Use concise language and include inline citations [doc:{doc_id}]."
    )


def _default_pro_system() -> str:
    return (
        "You are a RAG assistant with organization-wide access (Pro tier). "
        "Answer ONLY using the provided context. "
        "If evidence is insufficient, ask exactly one clarifying question OR present the closest related materials. "
        "Always include inline citations [doc:{doc_id}] and never fabricate sources."
    )


def _default_user_prefix_base() -> str:
    return "Q (base tier): "


def _default_user_prefix_pro() -> str:
    return "Q (pro tier): "


def _default_pro_opentext_system() -> str:
    # Tuned for comprehensive, structured OpenText answers; context-only by default.
    return (
        "You are an OpenText product expert. Answer ONLY using the supplied context. "
        "If the context is insufficient, say so and ask for the exact product/module/version or document. "
        "Write a comprehensive, structured answer with short paragraphs, bullets, and include inline citations [doc:{doc_id}] "
        "where relevant. Never fabricate sources."
    )


def _default_pro_opentext_prefix() -> str:
    return "Q (pro tier • OpenText): "


def get_prompts() -> Prompts:
    return Prompts(
        # Generic base/pro
        system_base=os.getenv("PROMPT_SYSTEM_BASE", _default_base_system()),
        system_pro=os.getenv("PROMPT_SYSTEM_PRO", _default_pro_system()),
        user_prefix_base=os.getenv("PROMPT_USER_PREFIX_BASE", _default_user_prefix_base()),
        user_prefix_pro=os.getenv("PROMPT_USER_PREFIX_PRO", _default_user_prefix_pro()),

        # OpenText specialization (optional; callers may ignore)
        system_pro_opentext=os.getenv("PROMPT_SYSTEM_PRO_OPENTEXT", _default_pro_opentext_system()),
        user_prefix_pro_opentext=os.getenv("PROMPT_USER_PREFIX_PRO_OPENTEXT", _default_pro_opentext_prefix()),
    )
