# app/utils/costs.py
MODEL_PRICING_MICRO = {
    # per 1M tokens, micro USD (ints)
    "gpt-3.5-turbo": {"input": 150_000, "output": 600_000},
    "gpt-4o-mini":   {"input": 150_000, "output": 600_000},
    "gpt-4o":        {"input": 500_000, "output": 1_500_000},
}

def estimate_cost_micro_usd(model: str, in_tokens: int, out_tokens: int) -> int:
    p = MODEL_PRICING_MICRO.get(model)
    if not p:
        return 0
    return int(in_tokens * (p["input"] / 1_000_000) + out_tokens * (p["output"] / 1_000_000))
