from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_settings
from .context import request_id_var, run_id_var, task_id_var, tenant_id_var, user_id_var

_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


def _trace_ids() -> tuple[str | None, str | None]:
    try:
        from opentelemetry import trace

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")
    except Exception:  # noqa: BLE001 - tracing is optional
        pass
    return None, None


class JsonlFormatter(logging.Formatter):
    """One JSON object per line. Correlation identifiers are always present."""

    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self.service = service
        self.env = env
        self.hostname = __import__("socket").gethostname()

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _trace_ids()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service,
            "env": self.env,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "trace_id": getattr(record, "trace_id", None) or trace_id,
            "span_id": getattr(record, "span_id", None) or span_id,
            "tenant_id": getattr(record, "tenant_id", None) or tenant_id_var.get(),
            "user_id": getattr(record, "user_id", None) or user_id_var.get(),
            "run_id": getattr(record, "run_id", None) or run_id_var.get(),
            "task_id": getattr(record, "task_id", None) or task_id_var.get(),
            "host": self.hostname,
            "pid": record.process,
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and key not in payload and not key.startswith("_")
        }
        if extra:
            payload["fields"] = _safe(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def _safe(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except (TypeError, ValueError):
        return str(value)


def configure_logging(service: str | None = None, level: str | None = None) -> None:
    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()
    service_name = service or settings.service_name
    root = logging.getLogger()
    if getattr(root, "_meridian_configured", False):
        return
    root.setLevel(resolved_level)
    formatter = JsonlFormatter(service_name, settings.env)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    try:
        log_path = Path(settings.log_dir).expanduser() / f"{service_name}.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=50 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("jsonl_file_logging_unavailable", exc_info=True)

    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    root._meridian_configured = True  # type: ignore[attr-defined]


class RunJsonlLogger:
    """Append-only per-run JSONL log, shared by API, scheduler and workers."""

    def __init__(self, log_dir: str, tenant_id: str, run_id: str) -> None:
        self.path = Path(log_dir).expanduser() / "runs" / tenant_id / f"{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, level: str, message: str, **fields: Any) -> dict[str, Any]:
        trace_id, span_id = _trace_ids()
        entry = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": level.upper(),
            "message": message,
            "request_id": request_id_var.get(),
            "trace_id": trace_id,
            "span_id": span_id,
            "run_id": run_id_var.get() if run_id_var.get() != "-" else fields.get("run_id"),
            "task_id": task_id_var.get() if task_id_var.get() != "-" else fields.get("task_id"),
            **{k: v for k, v in fields.items() if v is not None},
        }
        self.path.open("a", encoding="utf-8").write(json.dumps(entry, default=str) + "\n")
        return entry

    def read(self, limit: int = 2000) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"level": "WARN", "message": line})
        return entries


def get_logger(name: str = "meridian") -> logging.Logger:
    return logging.getLogger(name)
