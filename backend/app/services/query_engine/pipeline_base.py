# app/services/query_engine/pipeline_base.py
from __future__ import annotations
from typing import Dict, Any
import os

from .retrieval import ann_search, bm25_search, mmr_merge
from .confidence import score_answerability
from .synth import synthesize_answer, clarifier_message

# Optional telemetry
try:
    from opentelemetry import trace
    _tracer = trace.get_tracer(__name__)
except Exception:
    _tracer = None

# --- Env knobs (safe defaults) ---
BASE_ANN_K         = int(os.getenv("BASE_ANN_K", "24"))
BASE_BM25_K        = int(os.getenv("BASE_BM25_K", "24"))
BASE_SELECT_K      = int(os.getenv("BASE_SELECT_K", "6"))
BASE_MMR_ALPHA     = float(os.getenv("BASE_MMR_ALPHA", "0.75"))
BASE_CONF_SYNTH    = float(os.getenv("BASE_CONF_SYNTH", "0.72"))
BASE_CONF_CLARIFY  = float(os.getenv("BASE_CONF_CLARIFY", "0.50"))  # mid band

async def answer_query_base(user_id: str, query: str, scope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Base pipeline: session-scoped only, strict context answering.
      1) ANN + BM25 → MMR merge (k=BASE_SELECT_K)
      2) Score answerability:
         - >= BASE_CONF_SYNTH   → synthesize_answer (tier=base)
         - >= BASE_CONF_CLARIFY → clarifier_message (targeted follow-ups)
         - else                 → no_answer (no model-only fallback)
    """
    scope = {**scope, "session_scoped_only": True}

    # Retrieval
    ann   = await ann_search(query, scope, k=BASE_ANN_K)
    bm25  = await bm25_search(query, scope, k=BASE_BM25_K)
    merged = mmr_merge(query, ann, bm25, k=BASE_SELECT_K, alpha=BASE_MMR_ALPHA)

    # Telemetry
    if _tracer:
        sp = trace.get_current_span()
        sp.set_attribute("base.retrieval.ann_k", len(ann))
        sp.set_attribute("base.retrieval.bm25_k", len(bm25))
        sp.set_attribute("base.retrieval.selected_k", len(merged))

    # Confidence gating
    conf = score_answerability(merged)
    if _tracer:
        trace.get_current_span().set_attribute("base.answer.confidence", conf.value)

    if conf.value >= BASE_CONF_SYNTH:
        # Strictly answer from session context
        return await synthesize_answer(query, merged[:BASE_SELECT_K], tier="base")

    if conf.value >= BASE_CONF_CLARIFY:
        return await clarifier_message((conf.suggestions or [])[:3])

    # No sources → explicit decline (policy)
    return {
        "type": "no_answer",
        "message": "Not enough in-session material to answer.",
        "suggested_queries": (conf.suggestions or [])[:3],
    }
