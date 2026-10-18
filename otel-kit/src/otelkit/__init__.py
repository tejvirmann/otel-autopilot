"""otel-kit: thin, config-only OpenTelemetry distro.

One init() call sets resource attributes, OTLP export, PII scrubbing and the
common auto-instrumentations. It does NOT wrap the OTel API: application code
keeps using opentelemetry.trace / opentelemetry.metrics directly.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

__all__ = ["init", "business_span", "genai_call"]

_SENSITIVE_KEYS = re.compile(r"(authorization|cookie|password|secret|token|api[-_.]?key|set-cookie)", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def scrub_value(v):
    if isinstance(v, str):
        return _CARD.sub("[REDACTED_CARD]", _EMAIL.sub("[REDACTED_EMAIL]", v))
    return v


class _ScrubbingExporter(SpanExporter):
    """Redacts PII/secrets from span attributes just before export."""

    def __init__(self, inner: SpanExporter):
        self._inner = inner

    def export(self, spans):
        for s in spans:
            clean = {k: ("[REDACTED]" if _SENSITIVE_KEYS.search(k) else scrub_value(v))
                     for k, v in (s.attributes or {}).items()}
            s._attributes = clean  # ReadableSpan is frozen via API only; internal swap is intentional
            for ev in s.events:
                if ev.attributes:
                    ev._attributes = {k: scrub_value(v) for k, v in ev.attributes.items()}
        return self._inner.export(spans)

    def shutdown(self):
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        return self._inner.force_flush(timeout_millis)


def init(service_name: str, *, app=None, version: str | None = None, env: str | None = None):
    """Configure tracing + metrics. Pass the FastAPI `app` to auto-instrument routes."""
    resource = Resource.create({
        "service.name": service_name,
        "service.version": version or os.getenv("SERVICE_VERSION", "0.0.0"),
        "deployment.environment": env or os.getenv("DEPLOY_ENV", "dev"),
    })
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(_ScrubbingExporter(OTLPSpanExporter())))
    trace.set_tracer_provider(tp)
    metrics.set_meter_provider(MeterProvider(
        resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]))

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
    HTTPXClientInstrumentor().instrument()
    SQLite3Instrumentor().instrument()
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    return tp


@contextmanager
def business_span(name: str, **attributes):
    """Span for a business operation (e.g. 'checkout.charge'). Keep names low-cardinality."""
    tracer = trace.get_tracer("otelkit.business")
    with tracer.start_as_current_span(name) as span:
        for k, v in attributes.items():
            span.set_attribute(k, v)
        yield span


class _GenAI:
    def __init__(self, span, hist, attrs):
        self.span, self._hist, self._attrs = span, hist, attrs

    def record(self, input_tokens: int, output_tokens: int):
        self.span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        self.span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        self._hist.record(input_tokens, {**self._attrs, "gen_ai.token.type": "input"})
        self._hist.record(output_tokens, {**self._attrs, "gen_ai.token.type": "output"})


@contextmanager
def genai_call(system: str, model: str, operation: str = "chat"):
    """Span + token-usage metric following the OTel GenAI semantic conventions."""
    hist = metrics.get_meter("otelkit.genai").create_histogram(
        "gen_ai.client.token.usage", unit="{token}", description="Input and output tokens")
    attrs = {"gen_ai.system": system, "gen_ai.request.model": model, "gen_ai.operation.name": operation}
    with trace.get_tracer("otelkit.genai").start_as_current_span(f"{operation} {model}") as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        yield _GenAI(span, hist, attrs)
