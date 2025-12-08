from __future__ import annotations
from typing import List, Dict
from statistics import mean
from dataclasses import dataclass

@dataclass
class Conf:
    value: float
    suggestions: list[str]

def score_answerability(chunks: List[Dict]) -> Conf:
    if not chunks:
        return Conf(0.0, ["Try broader keywords", "Mention exact file/section"])
    max_sim = chunks[0].get("score", 0.0)
    avg_top5 = mean([c.get("score", 0.0) for c in chunks[:5]]) if len(chunks) >= 3 else max_sim
    src_div = len({c["doc_id"] for c in chunks[:5]})
    val = 0.6*max_sim + 0.25*avg_top5 + 0.15*min(src_div/3.0, 1.0)
    return Conf(min(1.0, val), ["Add product/version", "Specify doc title", "Narrow the topic"])
