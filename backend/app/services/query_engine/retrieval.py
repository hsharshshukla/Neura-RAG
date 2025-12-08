from __future__ import annotations
from typing import Dict, Any, List, Tuple
import asyncio
from app.telemetry.trace import span
from app.vector_store import search_vectors  # your existing function
from app.vector_scope import apply_scope     # your scope builder/filters

# If you already have BM25/text search, import here; otherwise stub it out.
async def _bm25_search(query: str, scope: Dict[str, Any], k: int) -> List[Dict[str, Any]]:
    # Replace with your bm25 adapter. If none, just return [].
    return []

@span("retrieval.ann")
async def ann_search(query: str, scope: Dict[str, Any], k=50, timeout_ms=250):
    scoped = apply_scope(scope)  # e.g., org_id, user_id, session_scoped_only
    # Expecting your search_vectors to return items like:
    # { "doc_id": str, "chunk_id": int, "text": str, "score": float, "meta": {...} }
    return await asyncio.wait_for(search_vectors(query=query, scope=scoped, k=k), timeout_ms/1000)

@span("retrieval.bm25")
async def bm25_search(query: str, scope: Dict[str, Any], k=50, timeout_ms=200):
    return await asyncio.wait_for(_bm25_search(query, scope, k), timeout_ms/1000)

@span("retrieval.parallel")
async def parallel_hybrid_search(query: str, scope: Dict[str, Any], ann_k=50, bm25_k=50):
    ann_task = asyncio.create_task(ann_search(query, scope, k=ann_k))
    bm_task  = asyncio.create_task(bm25_search(query, scope, k=bm25_k))
    ann, bm = await asyncio.gather(ann_task, bm_task)
    return ann, bm

def mmr_merge(
    query: str,
    ann: List[Dict[str, Any]],
    bm25: List[Dict[str, Any]],
    k: int = 12,
    alpha: float = 0.7,
    lambda_mmr: float = 0.5,
) -> List[Dict[str, Any]]:
    # Merge by normalized score (vector + text), then simple MMR to diversify across docs/sections.
    pool: dict[tuple[str,int|None], Dict[str, Any]] = {}
    for it in ann:
        pool[(it["doc_id"], it.get("chunk_id"))] = {**it, "ann": it["score"], "bm25": 0.0}
    for it in bm25:
        key = (it["doc_id"], it.get("chunk_id"))
        if key in pool:
            pool[key]["bm25"] = it["score"]
        else:
            pool[key] = {**it, "ann": 0.0, "bm25": it["score"]}

    for it in pool.values():
        it["score"] = alpha * it.get("ann", 0.0) + (1 - alpha) * it.get("bm25", 0.0)

    cand = sorted(pool.values(), key=lambda x: x["score"], reverse=True)[: min(50, len(pool))]
    selected: List[Dict[str, Any]] = []
    seen_docs: set[str] = set()
    while cand and len(selected) < k:
        # very light diversity: prefer new doc_ids early
        cand.sort(key=lambda x: (x["doc_id"] in seen_docs, -x["score"]))
        pick = cand.pop(0)
        selected.append(pick)
        seen_docs.add(pick["doc_id"])
    return selected
