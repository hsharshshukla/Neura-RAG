# app/services/query_engine/synth.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os

from app.telemetry.trace import span
from .prompt_config import get_prompts

# -----------------------------
# Config (env-driven)
# -----------------------------
OPENAI_MODEL_PRO = os.getenv("OPENAI_MODEL_PRO", "gpt-5")
MAX_CTX_CHARS = int(os.getenv("SYNTH_MAX_CONTEXT_CHARS", "16000"))
DEFAULT_TEMP = float(os.getenv("SYNTH_TEMPERATURE", "0.2"))

# Optional OpenTelemetry
try:
    from opentelemetry import trace
    _tracer = trace.get_tracer(__name__)
except Exception:
    _tracer = None


# Plug your OpenAI client (SDK/httpx). Return {"content": "...", "usage": {...}} if possible.
async def _openai_chat(model: str, system: str, user: str, **kwargs) -> Dict[str, Any]:
    # Implement with httpx/OpenAI SDK; recommended keys in response:
    #   {"content": str, "usage": {"prompt_tokens": int, "completion_tokens": int}}
    ...
    # raise NotImplementedError if not wired yet


def _dedupe_keep_order(chunks: List[Dict]) -> List[Dict]:
    seen = set()
    out: List[Dict] = []
    for c in chunks:
        did = c.get("doc_id")
        if did in seen:
            continue
        seen.add(did)
        out.append(c)
    return out


def _pack_context(chunks: List[Dict], token_budget_chars: int = MAX_CTX_CHARS) -> str:
    """
    Pack chunk list into a single context block, respecting a char (rough token) budget.
    Expects chunk shape: {"doc_id": str|int, "text": str, "meta": {"title": str, ...}}
    """
    chunks = _dedupe_keep_order(chunks)
    buf, size = [], 0
    for c in chunks:
        title = (c.get("meta", {}) or {}).get("title", "")
        text = c.get("text") or c.get("page_content") or ""
        if not text:
            continue
        seg = f"[doc:{c.get('doc_id')}::{title}]\n{text}\n"
        size += len(seg)
        buf.append(seg)
        if size >= token_budget_chars:
            break
    return "\n---\n".join(buf)


def _choose_model(tier: str, ctx_len: int, override: Optional[str]) -> str:
    if override:
        return override
    # Heuristic: small context -> lighter model; else bigger model
    if tier == "pro":
        # Let Pro default to PRO model when context is large; else step down for latency/cost.
        return OPENAI_MODEL_PRO if ctx_len > 6000 else "gpt-4o"
    # Base
    return "gpt-4o-mini" if ctx_len <= 6000 else "gpt-4o"


@span("llm.synthesize")
async def synthesize_answer(
    query: str,
    chunks: List[Dict],
    tier: str,
    *,
    model_override: Optional[str] = None,
    system_override: Optional[str] = None,
    user_prefix_override: Optional[str] = None,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Synthesize a grounded answer from retrieved chunks.
    Backward compatible with old signature; callers can now pass overrides.

    Returns:
      {
        "type": "answer",
        "model": <str>,
        "content": <str>,
        "citations": [{"doc_id": ..., "title": ...}, ...],
      }
    """
    prompts = get_prompts()
    system = system_override or (prompts.system_pro if tier == "pro" else prompts.system_base)
    user_prefix = user_prefix_override or (prompts.user_prefix_pro if tier == "pro" else prompts.user_prefix_base)

    ctx = _pack_context(chunks)
    user = f"{user_prefix}{query}\n\nContext:\n{ctx}"
    model = _choose_model(tier, len(ctx), model_override)
    temp = DEFAULT_TEMP if temperature is None else float(temperature)

    # Optional OTEL attributes before call
    if _tracer:
        sp = trace.get_current_span()
        sp.set_attribute("synth.tier", tier)
        sp.set_attribute("synth.model.selected", model)
        sp.set_attribute("synth.ctx_chars", len(ctx))
        sp.set_attribute("synth.num_chunks", len(chunks))

    out = await _openai_chat(model=model, system=system, user=user, temperature=temp)

    content = (out or {}).get("content", "")
    usage = (out or {}).get("usage", {}) or {}

    # Optional OTEL attributes after call
    if _tracer and usage:
        sp = trace.get_current_span()
        try:
            sp.set_attribute("llm.prompt_tokens", int(usage.get("prompt_tokens") or 0))
            sp.set_attribute("llm.completion_tokens", int(usage.get("completion_tokens") or 0))
        except Exception:
            pass

    return {
        "type": "answer",
        "model": model,
        "content": content,
        "citations": [
            {"doc_id": c.get("doc_id"), "title": (c.get("meta", {}) or {}).get("title")}
            for c in _dedupe_keep_order(chunks)[:8]
        ],
    }


@span("llm.clarify")
async def clarifier_message(suggestions: list[str]) -> Dict[str, Any]:
    return {
        "type": "clarify",
        "message": "I found partial matches. Do you mean one of these? You can also specify a file name or section.",
        "suggested": suggestions[:3],
    }
