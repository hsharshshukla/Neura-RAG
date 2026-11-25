"""Run Neura for disposable P0 acceptance without changing production modules.

The deterministic mode keeps browser and isolation checks reproducible while using
the real FastAPI application, PostgreSQL, Qdrant, storage, and TKP HTTP bridge.
Set P0_PROVIDER_MODE=real to leave the configured OpenAI provider untouched.
"""

from __future__ import annotations

import hashlib
import json
import math
import os


def _vector(text: str) -> list[float]:
    dimension = int(os.environ["EMBED_DIM"])
    values = [0.0] * dimension
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        values[int.from_bytes(digest[:4], "big") % dimension] += 1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


if os.getenv("P0_PROVIDER_MODE", "deterministic") == "deterministic":
    from app import vector_store
    from app.services import llm

    vector_store._embed_texts = lambda texts: [_vector(text) for text in texts]
    vector_store._embed_query = _vector

    def controlled_chat_complete(messages, **_kwargs):
        policy = messages[0]["content"]
        payload = json.loads(messages[1]["content"])
        if "Rewrite a contextual follow-up" in policy:
            return (
                json.dumps(
                    {
                        "requires_context": True,
                        "context_resolved": True,
                        "standalone_query": payload["current_question"],
                        "ambiguity_reason": None,
                    }
                ),
                "stop",
                {},
            )
        if "Generate a runtime answer" in policy:
            evidence = payload["approved_evidence"]
            claims = [
                {
                    "claim_id": f"C{index}",
                    "text": item["content"][:500],
                    "evidence_ids": [item["evidence_id"]],
                }
                for index, item in enumerate(evidence, 1)
            ]
            return (
                json.dumps(
                    {
                        "insufficient_evidence": not bool(claims),
                        "claims": claims,
                        "confidence": 0.99 if claims else 0,
                    }
                ),
                "stop",
                {},
            )
        if "Validate factual entailment" in policy:
            return (
                json.dumps(
                    {
                        "results": [
                            {"claim_id": item["claim_id"], "supported": True}
                            for item in payload["claims"]
                        ],
                        "contradictory_evidence": False,
                    }
                ),
                "stop",
                {},
            )
        raise RuntimeError("unexpected deterministic acceptance prompt")

    llm.chat_complete = controlled_chat_complete

import uvicorn

from app.main import app

uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.environ["P0_NEURA_PORT"]),
    log_level=os.getenv("P0_LOG_LEVEL", "warning"),
)
