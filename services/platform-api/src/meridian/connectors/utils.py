from __future__ import annotations

import fnmatch
import mimetypes
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from edp_connector_sdk import ConnectorError

MEDIA_TYPES = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".ndjson": "application/x-ndjson",
    ".xml": "application/xml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}


def guess_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return MEDIA_TYPES.get(suffix) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def assert_safe_relative(path: str) -> str:
    normalised = path.replace("\\", "/")
    if normalised.startswith("/") or re.match(r"^[A-Za-z]:", normalised):
        raise ConnectorError("Path must be relative to the configured root.", code="invalid_path")
    parts = [part for part in normalised.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ConnectorError("Path traversal is not allowed.", code="invalid_path")
    return "/".join(parts)


def within(path: Path, roots: list[Path]) -> bool:
    resolved = path.expanduser().resolve()
    for root in roots:
        try:
            resolved.relative_to(root.expanduser().resolve())
            return True
        except ValueError:
            continue
    return False


def resolve_path(path: str, root: str | None, allowed_roots: list[Path]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        base = Path(root).expanduser() if root else (allowed_roots[0] if allowed_roots else Path.cwd())
        candidate = base / candidate
    candidate = candidate.resolve()
    roots = [Path(root).expanduser().resolve()] if root else allowed_roots
    if roots and not within(candidate, roots):
        raise ConnectorError(
            "File path is outside the configured allowed roots.", code="path_not_allowed"
        )
    return candidate


def glob_files(root: Path, pattern: str, max_files: int) -> list[Path]:
    files = [path for path in root.glob(pattern) if path.is_file()]
    return sorted(files)[:max_files]


def find_files(base: Path, pattern: str | None, recursive: bool, max_files: int) -> list[Path]:
    if base.is_file():
        return [base]
    if pattern:
        iterator = base.rglob(pattern) if recursive else base.glob(pattern)
        return sorted(path for path in iterator if path.is_file())[:max_files]
    iterator = base.rglob("*") if recursive else base.iterdir()
    return sorted(path for path in iterator if path.is_file())[:max_files]


def extract_json_path(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def records_from_payload(payload: Any, path: str | None = None) -> list[dict[str, Any]]:
    selected = extract_json_path(payload, path)
    if selected is None and path:
        raise ConnectorError(f"JSON records path '{path}' was not found.", code="records_path_missing")
    if isinstance(selected, list):
        return [item if isinstance(item, dict) else {"value": item} for item in selected]
    if isinstance(selected, dict):
        for key in ("data", "items", "records", "results", "rows"):
            candidate = selected.get(key)
            if isinstance(candidate, list):
                return [item if isinstance(item, dict) else {"value": item} for item in candidate]
        return [selected]
    return [{"value": selected}]


def utc_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def match_name(name: str, patterns: str | None) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name, item.strip()) for item in patterns.split(",") if item.strip())
