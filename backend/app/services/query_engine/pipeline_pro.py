# app/services/query_engine/pipeline_pro.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import os
import anyio

from .retrieval import parallel_hybrid_search, mmr_merge
from .confidence import score_answerability
from .synth import synthesize_answer, clarifier_message

# Optional telemetry
try:
    from opentelemetry import trace
    _tracer = trace.get_tracer(__name__)
except Exception:
    _tracer = None

# --- Env knobs ---
PRO_ANN_K         = int(os.getenv("PRO_ANN_K", "50"))
PRO_BM25_K        = int(os.getenv("PRO_BM25_K", "50"))
PRO_SELECT_K      = int(os.getenv("PRO_SELECT_K", "12"))
PRO_MMR_ALPHA     = float(os.getenv("PRO_MMR_ALPHA", "0.7"))
PRO_CONF_SYNTH    = float(os.getenv("PRO_CONF_SYNTH", "0.75"))
PRO_CONF_CLARIFY  = float(os.getenv("PRO_CONF_CLARIFY", "0.45"))

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

# Fallback toggle: if true, Pro can answer without sources when retrieval is weak/empty
PRO_MODEL_ONLY_DEFAULT = _env_bool("PRO_MODEL_ONLY_DEFAULT", True)

# Pro model + OpenText specialization
GPT5_MODEL = os.getenv("OPENAI_MODEL_PRO", "gpt-5")
PROMPT_SYSTEM_PRO_OPENTEXT = os.getenv(
    "PROMPT_SYSTEM_PRO_OPENTEXT",
    "You are an OpenText product expert. Answer ONLY using the supplied context. "
    "If the context is insufficient, say so and ask for the exact product/module/version or document. "
    "Write a concise, structured answer with clear bullets."
)
_OPENTEXT_ALIASES = [
    x.strip().lower()
    for x in os.getenv(
        "OPENTEXT_PRODUCT_ALIASES",
        "opentext,content server,exstream,xcp,appworks,documentum,teamsite,"
        "infoarchive,extended ecm,xecm,magellan,core content,core capture,archivelink,archive link"
    ).split(",")
    if x.strip()
]

def _is_opentext_query(q: str) -> bool:
    ql = (q or "").lower()
    return any(alias in ql for alias in _OPENTEXT_ALIASES)

async def _model_only_answer(query: str, model_name: str) -> str:
    """
    Direct model-only call (no citations). We intentionally DO NOT pass temperature,
    as some deployments only support the default.
    """
    def _call() -> str:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system",
                 "content": "You are an expert enterprise software assistant. Answer clearly and concisely. "
                            "If something is unknown, say so plainly."},
                {"role": "user", "content": query},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    return await anyio.to_thread.run_sync(_call)

async def _maybe_synthesize_with_opentext(
    query: str,
    merged: List[dict],
) -> Optional[Dict[str, Any]]:
    """
    If the query is OpenText-ish, try to synthesize with the domain prompt.
    Only return an actual answer/clarifier; otherwise return None so the pipeline
    can continue to model-only fallback if enabled.
    """
    if not _is_opentext_query(query):
        return None

    conf = score_answerability(merged)
    if _tracer:
        trace.get_current_span().set_attribute("pro.answer.confidence", conf.value)

    if conf.value >= PRO_CONF_SYNTH and merged:
        try:
            return await synthesize_answer(
                query,
                merged[:PRO_SELECT_K],
                tier="pro",
                model_override=GPT5_MODEL,
                system_override=PROMPT_SYSTEM_PRO_OPENTEXT,
                # no temperature argument on purpose
            )
        except TypeError:
            # Back-compat in case synthesize_answer signature differs
            return await synthesize_answer(query, merged[:PRO_SELECT_K], tier="pro")

    if conf.value >= PRO_CONF_CLARIFY:
        suggestions = conf.suggestions or [
            "Specify the product and version (e.g., Extended ECM 23.x).",
            "Which module/connector (SAP, Salesforce, SuccessFactors)?",
            "Share the document title/section you’re using.",
        ]
        return await clarifier_message(suggestions)

    # Low confidence → let the main pipeline decide (possibly model-only)
    return None

async def answer_query_pro(
    user_id: str,
    query: str,
    scope: Dict[str, Any],
    allow_model_only: bool = False,
) -> Dict[str, Any]:
    """
    Pro pipeline with:
      - Hybrid retrieval (ANN+BM25) → MMR merge (k=PRO_SELECT_K)
      - Confidence gating
      - OpenText-aware fast path (answer/clarify only)
      - Optional model-only fallback when no relevant sources
    """
    scope = {**scope, "session_scoped_only": False}

    # Retrieval
    ann, bm25 = await parallel_hybrid_search(query, scope, ann_k=PRO_ANN_K, bm25_k=PRO_BM25_K)
    merged = mmr_merge(query, ann, bm25, k=PRO_SELECT_K, alpha=PRO_MMR_ALPHA)

    if _tracer:
        sp = trace.get_current_span()
        sp.set_attribute("pro.retrieval.ann_k", len(ann))
        sp.set_attribute("pro.retrieval.bm25_k", len(bm25))
        sp.set_attribute("pro.retrieval.selected_k", len(merged))

    # OpenText fast-path: only short-circuit if it yields an answer/clarifier
    ot = await _maybe_synthesize_with_opentext(query, merged)
    if ot is not None and ot.get("type") in {"answer", "clarify"}:
        return ot

    # Normal Pro behavior (non-OpenText or low-confidence OpenText)
    conf = score_answerability(merged)
    if _tracer:
        trace.get_current_span().set_attribute("pro.answer.confidence", conf.value)

    if conf.value >= PRO_CONF_SYNTH:
        # Synthesize with sources
        return await synthesize_answer(query, merged[:PRO_SELECT_K], tier="pro")

    if conf.value >= PRO_CONF_CLARIFY:
        # Ask for clarifying info
        return await clarifier_message(conf.suggestions)

    # No strong sources → maybe model-only
    effective_model_only = bool(allow_model_only or PRO_MODEL_ONLY_DEFAULT)
    if effective_model_only:
        text = await _model_only_answer(query, GPT5_MODEL)
        return {
            "type": "answer",
            "content": text,
            "model": GPT5_MODEL,
            "citations": [],
            "banner": "AI answer (no sources)",
            "mode": "model_only_no_sources",
        }

    # Otherwise, instruct the user
    return {
        "type": "no_answer",
        "message": "I couldn’t find relevant sources in your documents. You can refine the question or enable “Answer without sources”.",
        "suggested_queries": (conf.suggestions or [])[:5],
        "allow_web_option": True,
    }
