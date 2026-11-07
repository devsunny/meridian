from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from .config import get_settings

logger = logging.getLogger("meridian.telemetry")
_configured = False


def configure_telemetry(service_name: str | None = None) -> None:
    """Configure OTLP/HTTP traces + metrics. No-op when disabled, never fatal."""
    global _configured
    if _configured:
        return
    settings = get_settings()
    if not settings.otel_enabled:
        _configured = True
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = settings.otel_exporter_otlp_endpoint or "http://localhost:4318"
        resource = Resource.create(
            {
                "service.name": service_name or settings.service_name,
                "service.version": settings.version,
                "deployment.environment.name": settings.env,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics")
                )
            ],
        )
        try:
            from opentelemetry import metrics

            metrics.set_meter_provider(meter_provider)
        except Exception:  # noqa: BLE001
            pass
        _configured = True
        logger.info("otel_configured", extra={"endpoint": endpoint})
    except Exception:  # noqa: BLE001
        logger.exception("otel_configuration_failed")


def instrument_fastapi(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
    except Exception:  # noqa: BLE001
        logger.debug("fastapi_instrumentation_unavailable", exc_info=True)


def instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        logger.debug("httpx_instrumentation_unavailable", exc_info=True)


def instrument_sqlalchemy(engine) -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)
    except Exception:  # noqa: BLE001
        logger.debug("sqlalchemy_instrumentation_unavailable", exc_info=True)


@contextmanager
def span(name: str, attributes: dict | None = None) -> Iterator[object | None]:
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("meridian")
        current_span = tracer.start_as_current_span(name)
    except Exception:  # noqa: BLE001 - tracing must never break business logic
        yield None
        return
    with current_span as current:
        for key, value in (attributes or {}).items():
            if value is not None:
                current.set_attribute(key, str(value))
        yield current
