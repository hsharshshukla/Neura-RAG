# app/telemetry/trace.py
from __future__ import annotations
import os, time, asyncio, logging
from functools import wraps
from typing import Callable, Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Optional: metrics/logs can be added later.

_tracer_initialized = False

def init_tracer() -> None:
    global _tracer_initialized
    if _tracer_initialized:
        return
    svc = os.getenv("OTEL_SERVICE_NAME", "neura-chat")
    env = os.getenv("OTEL_ENVIRONMENT", "dev")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")

    resource = Resource.create({
        "service.name": svc,
        "deployment.environment": env,
        # add more: service.version, cloud.region, etc.
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=_parse_headers(headers))
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _tracer_initialized = True

def _parse_headers(h: str) -> dict[str, str]:
    if not h: return {}
    out = {}
    for pair in h.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def get_tracer(name: str = "neura") -> trace.Tracer:
    return trace.get_tracer(name)

def span(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that creates an OTEL span around a sync/async function."""
    def decorator(func: Callable[..., Any]):
        tracer = get_tracer(func.__module__)
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def aw(*args, **kwargs):
                with tracer.start_as_current_span(name) as sp:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        sp.record_exception(e)
                        sp.set_status(trace.status.Status(trace.status.StatusCode.ERROR, str(e)))
                        raise
            return aw
        else:
            @wraps(func)
            def sw(*args, **kwargs):
                with tracer.start_as_current_span(name) as sp:
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        sp.record_exception(e)
                        sp.set_status(trace.status.Status(trace.status.StatusCode.ERROR, str(e)))
                        raise
            return sw
    return decorator
