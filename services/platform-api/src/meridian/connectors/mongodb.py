from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from edp_connector_sdk import (
    ConfigField,
    ConnectionTest,
    Connector,
    ConnectorContext,
    ConnectorError,
    RecordBatch,
    Resource,
    register,
)

from ..secrets import secret_for
from .utils import json_safe


@register
class MongoConnector(Connector):
    type = "mongodb"
    label = "MongoDB / Document DB"
    category = "database"
    description = "Read collections from MongoDB-compatible document databases."
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("uri_ref", "Connection URI secret", "secret", True, "", "env:MONGO_URI"),
        ConfigField("database", "Database", "string", True),
        ConfigField("collection", "Collection", "string", False),
        ConfigField("filter", "Filter JSON", "textarea", False, "{}"),
        ConfigField("limit", "Row limit", "integer", False, 100000),
    ]
    icon = "database"

    def _client(self, secrets: dict[str, str | None]):
        try:
            import pymongo
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConnectorError(
                "MongoDB support is not installed. Install the platform 'mongo' extra.",
                code="mongo_support_missing",
            ) from exc
        uri = secret_for({}, secrets, "uri")
        if not uri:
            raise ConnectorError("A MongoDB URI secret is required.", code="missing_uri")
        return pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            client = self._client(secrets)
            client.admin.command("ping")
            return ConnectionTest(True, "MongoDB ping succeeded.", int((time.perf_counter() - started) * 1000))
        except ConnectorError as exc:
            return ConnectionTest(False, str(exc), int((time.perf_counter() - started) * 1000))
        except Exception as exc:  # noqa: BLE001
            return ConnectionTest(False, f"MongoDB failed: {exc.__class__.__name__}")

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        client = self._client(secrets)
        database = client[str(config["database"])]
        return [
            Resource(id=name, name=name, kind="collection", path=name, metadata={"database": database.name})
            for name in database.list_collection_names()[:500]
        ]

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        import json

        client = self._client(secrets)
        database = client[str(config["database"])]
        collection = database[str(config.get("collection") or resource.name)]
        try:
            query = json.loads(config.get("filter") or "{}")
        except ValueError as exc:
            raise ConnectorError("Filter must be valid JSON.", code="invalid_filter") from exc
        limit = min(int((options or {}).get("limit", config.get("limit", 100_000))), 1_000_000)
        records = []
        for document in collection.find(query).limit(limit):
            document["_id"] = str(document["_id"])
            records.append(json_safe(document))
        yield RecordBatch(records=records, source_uri=resource.id)
