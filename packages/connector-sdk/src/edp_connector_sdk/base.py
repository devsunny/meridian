from __future__ import annotations

import abc
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from .types import ConfigField, ConnectionTest, RecordBatch, Resource


class ConnectorError(RuntimeError):
    """A safe, user-presentable connector failure. Never include secrets in the message."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "connector_error",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


class SecretResolver(Protocol):
    """Resolves an opaque secret reference. The platform injects the implementation."""

    def __call__(self, ref: str | None) -> str | None: ...


@dataclass
class ConnectorContext:
    """Execution context passed to every connector method."""

    tenant_id: str
    request_id: str
    run_id: str | None = None
    task_id: str | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("meridian.connector"))
    _resolver: SecretResolver | None = field(default=None, repr=False)

    def resolve_secret(self, ref: str | None) -> str | None:
        if not ref:
            return None
        if self._resolver is None:
            raise ConnectorError(
                "No secret resolver is configured for this connector execution.",
                code="secret_resolver_missing",
            )
        return self._resolver(ref)


class Connector(abc.ABC):
    """Base class for a Meridian connector.

    Connectors are instantiated once per execution and must be stateless between calls.
    """

    type: str = ""
    label: str = ""
    category: str = "other"
    description: str = ""
    capabilities: tuple[str, ...] = ("test", "discover", "read")
    config_schema: ClassVar[list[ConfigField]] = []
    icon: str = "plug"

    @abc.abstractmethod
    def test(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
    ) -> ConnectionTest | dict[str, Any]:
        """Check reachability and authentication without changing source state."""

    @abc.abstractmethod
    def discover(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
    ) -> Iterable[Resource]:
        """List resources that can be ingested."""

    @abc.abstractmethod
    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        """Yield bounded batches from one resource."""

    # Convenience for the control plane / UI.
    def manifest(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label or self.type,
            "category": self.category,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "config_schema": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.type,
                    "required": f.required,
                    "default": f.default,
                    "help": f.help,
                    "options": list(f.options),
                }
                for f in self.config_schema
            ],
            "icon": self.icon,
        }
