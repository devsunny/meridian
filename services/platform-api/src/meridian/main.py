from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    assist,
    auth,
    catalog,
    governance,
    ingestions,
    integrations,
    pipelines,
    runs,
    schedules,
    security,
    sources,
    system,
    terminal,
)
from .api.deps import new_request_id_header
from .config import get_settings
from .context import request_id_var, tenant_id_var, user_id_var
from .db import db_health, init_db, metrics
from .logging_setup import configure_logging, get_logger
from .telemetry import configure_telemetry, instrument_fastapi

settings = get_settings()
configure_logging(settings.service_name)
configure_telemetry(settings.service_name)
logger = get_logger("meridian.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(seed=True)
    instrument_fastapi(_app)
    logger.info(
        "api_started",
        extra={"version": settings.version, "env": settings.env, "database": settings.database_url.split("@")[-1]},
    )
    yield
    logger.info("api_stopped")

app = FastAPI(
    title="Meridian Data Platform API",
    version=settings.version,
    description=(
        "Governed ingestion, metadata, DAG orchestration, security and AI enablement. "
        "Every response carries X-Request-ID; every log line is JSONL."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Trace-ID"],
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = new_request_id_header(request)
    token = request_id_var.set(request_id)
    request.state.request_id = request_id
    started = time.perf_counter()
    route = request.url.path
    try:
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if route not in {"/health/live", "/health/ready", "/metrics"}:
            metrics.inc("meridian_http_requests", method=request.method, status=str(response.status_code))
            metrics.observe("meridian_http_request_seconds", elapsed, method=request.method)
            logger.info(
                "http_request",
                extra={
                    "method": request.method,
                    "path": route,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 2),
                    "client_ip": request.client.host if request.client else "",
                },
            )
        return response
    except Exception:
        elapsed = time.perf_counter() - started
        logger.exception(
            "http_request_error",
            extra={"method": request.method, "path": route, "duration_ms": round(elapsed * 1000, 2)},
        )
        raise
    finally:
        request_id_var.reset(token)
        tenant_id_var.set("-")
        user_id_var.set("-")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", request_id_var.get())
    return JSONResponse(
        status_code=exc.status_code,
        headers={**(getattr(exc, "headers", None) or {}), "X-Request-ID": request_id},
        content={
            "type": "about:blank",
            "title": exc.detail if isinstance(exc.detail, str) else "Request failed",
            "status": exc.status_code,
            "detail": exc.detail,
            "request_id": request_id,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", request_id_var.get())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        headers={"X-Request-ID": request_id},
        content={
            "type": "about:blank",
            "title": "Request validation failed",
            "status": 422,
            "detail": jsonable_encoder(exc.errors()),
            "request_id": request_id,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", request_id_var.get())
    logger.exception("unhandled_exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        headers={"X-Request-ID": request_id},
        content={
            "type": "about:blank",
            "title": "Internal server error",
            "status": 500,
            "detail": "The request could not be completed. Quote the request id when contacting support.",
            "request_id": request_id,
        },
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "name": "Meridian Data Platform",
        "version": settings.version,
        "api": settings.api_prefix,
        "docs": "/docs",
        "health": "/health/live",
    }


@app.get("/health/live", tags=["health"])
def health_live() -> dict:
    return {"status": "ok", "service": settings.service_name, "request_id": request_id_var.get()}


@app.get("/health/ready", tags=["health"])
def health_ready() -> JSONResponse:
    ok, message = db_health()
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ready" if ok else "not_ready",
            "database": {"ok": ok, "message": message},
            "request_id": request_id_var.get(),
        },
    )


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


for router in (
    auth.router,
    system.router,
    sources.router,
    ingestions.router,
    pipelines.router,
    schedules.router,
    runs.router,
    catalog.router,
    governance.router,
    security.router,
    integrations.router,
    assist.router,
    terminal.router,
):
    app.include_router(router, prefix=settings.api_prefix)

# Avoid unused import warnings for the logging module in frozen builds.
_ = logging
