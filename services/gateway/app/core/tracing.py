from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import get_settings

_configured = False


def configure_tracing(app) -> None:
    global _configured
    settings = get_settings()
    if not _configured:
        resource = Resource.create({"service.name": settings.service_name, "service.version": settings.version})
        provider = TracerProvider(resource=resource)
        if settings.otel_enabled and settings.otel_exporter_otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        _configured = True
    FastAPIInstrumentor.instrument_app(app)
