"""Meridian connector SDK.

The SDK is deliberately small: dataclasses plus an abstract base class. The platform owns
orchestration, secrets, storage, retries, metadata and governance; connectors own source I/O.
"""

from .base import Connector, ConnectorContext, ConnectorError, SecretResolver
from .registry import available_connectors, get_connector, register
from .types import (
    ConfigField,
    ConnectionTest,
    RawAsset,
    RecordBatch,
    Resource,
    SchemaField,
)

__all__ = [
    "ConfigField",
    "ConnectionTest",
    "Connector",
    "ConnectorContext",
    "ConnectorError",
    "RawAsset",
    "RecordBatch",
    "Resource",
    "SchemaField",
    "SecretResolver",
    "available_connectors",
    "get_connector",
    "register",
]

__version__ = "0.1.0"
