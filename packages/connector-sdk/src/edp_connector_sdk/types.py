from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConfigField:
    """A single UI/config field declared by a connector."""

    name: str
    label: str
    type: str = "string"  # string | secret | integer | boolean | select | textarea
    required: bool = False
    default: Any = None
    help: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resource:
    """A discoverable source resource (table, file, folder, object, ...)."""

    id: str
    name: str
    kind: str = "file"  # table | file | folder | object | collection | document
    path: str | None = None
    size: int | None = None
    modified_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchemaField:
    name: str
    type: str = "string"
    nullable: bool = True
    description: str = ""


@dataclass
class RawAsset:
    """An opaque source object that the platform will parse (PDF, DOCX, XLSX, XML, ...)."""

    filename: str
    content: bytes
    media_type: str = "application/octet-stream"
    source_uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecordBatch:
    """One bounded batch of rows or one raw asset.

    Connectors should normally emit records for tabular sources and `RawAsset` for files that
    require platform parsing (documents, spreadsheets, XML). Both may be present: the platform
    consumes `records` first and parses `raw` when records are empty.
    """

    records: list[dict[str, Any]] = field(default_factory=list)
    schema: list[SchemaField] = field(default_factory=list)
    source_uri: str = ""
    raw: RawAsset | None = None
    cursor: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConnectionTest:
    ok: bool
    message: str
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
        }
