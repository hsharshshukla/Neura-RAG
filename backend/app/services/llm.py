# app/services/llm.py
from typing import List, Tuple, Dict, Any, AsyncGenerator
import os
from openai import OpenAI
from app.utils.openai_helpers import usage_to_dict

# One client per process (httpx pooling)
_client = OpenAI()  # picks OPENAI_API_KEY from env

DEFAULT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o")  # override via env if needed


def chat_complete(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> Tuple[str, str, Dict[str, int]]:
    """
    Non-streaming chat completion. Returns (text, finish_reason, usage_dict).
    """
    resp = _client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        timeout=timeout,  # httpx timeout inside SDK
    )
    text = (resp.choices[0].message.content or "").strip()
    finish_reason = getattr(resp.choices[0], "finish_reason", None)
    usage = usage_to_dict(resp.usage)
    return text, finish_reason, usage


async def chat_complete_stream(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    timeout: float = 90.0,
) -> AsyncGenerator[str, None]:
    """
    Minimal streaming generator that yields plain text chunks.
    Caller is responsible for persisting on completion.
    """
    # We use a simple system+user message shape to keep parity with your non-stream path
    messages = [
        {"role": "system", "content": os.getenv("PROMPT_SYSTEM_BASE", "You are a helpful assistant.")},
        {"role": "user", "content": prompt},
    ]

    # The OpenAI SDK yields events when stream=True
    stream = _client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=True,
        timeout=timeout,
    )
    # Iterate over deltas; only yield actual text
    for event in stream:
        try:
            delta = event.choices[0].delta
            if getattr(delta, "content", None):
                yield delta.content
        except Exception:
            # ignore malformed chunks
            continue
