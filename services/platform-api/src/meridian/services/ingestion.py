from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edp_connector_sdk import (
    ConnectorContext,
    ConnectorError,
    RawAsset,
    Resource,
    available_connectors,
    get_connector,
)
from sqlalchemy.orm import Session

from ..logging_setup import get_logger
from ..models import Connection, Ingestion
from ..parsers import ParsedAsset, parse_asset
from ..secrets import Resolver, collect_secrets, secret_for
from ..storage import get_storage
from .datasets import save_dataset

logger = get_logger("meridian.ingestion")


@dataclass
class DiscoveryResult:
    resources: list[dict[str, Any]]
    connector: dict[str, Any]


def connector_catalog() -> list[dict[str, Any]]:
    import meridian.connectors  # noqa: F401 - register built-ins

    return [connector().manifest() for connector in available_connectors().values()]


def _context(tenant_id: str, request_id: str, run_id: str | None = None) -> ConnectorContext:
    return ConnectorContext(
        tenant_id=tenant_id,
        request_id=request_id,
        run_id=run_id,
        logger=get_logger("meridian.connector"),
        _resolver=Resolver(),
    )


def _connector(connection: Connection):
    import meridian.connectors  # noqa: F401 - ensure first-party registrations

    try:
        return get_connector(connection.type)
    except KeyError as exc:
        raise ConnectorError(
            f"Connector type '{connection.type}' is not installed.",
            code="connector_not_installed",
        ) from exc


def test_connection(connection: Connection, request_id: str) -> dict[str, Any]:
    connector = _connector(connection)
    context = _context(connection.tenant_id, request_id)
    secrets = collect_secrets(connection.config, connection.secret_ref)
    result = connector.test(context, connection.config, secrets)
    return result.as_dict() if hasattr(result, "as_dict") else dict(result)


def discover_connection(
    connection: Connection, request_id: str, options: dict[str, Any] | None = None
) -> DiscoveryResult:
    connector = _connector(connection)
    context = _context(connection.tenant_id, request_id)
    secrets = collect_secrets(connection.config, connection.secret_ref)
    resources = list(connector.discover(context, connection.config, secrets))
    return DiscoveryResult(
        resources=[
            {
                "id": resource.id,
                "name": resource.name,
                "kind": resource.kind,
                "path": resource.path,
                "size": resource.size,
                "modified_at": resource.modified_at,
                "metadata": resource.metadata,
            }
            for resource in resources
        ],
        connector=connector.manifest(),
    )


def _select_resource(
    connection: Connection,
    spec: dict[str, Any],
    request_id: str,
    options: dict[str, Any],
) -> Resource:
    selector = spec.get("resource") or spec.get("resource_id") or options.get("resource")
    if isinstance(selector, dict):
        return Resource(
            id=str(selector.get("id") or selector.get("path") or selector.get("name") or "source"),
            name=str(selector.get("name") or "source"),
            kind=str(selector.get("kind") or "file"),
            path=selector.get("path"),
            size=selector.get("size"),
            metadata=selector.get("metadata") or {},
        )
    if not selector:
        discovery = discover_connection(connection, request_id)
        if not discovery.resources:
            raise ConnectorError("No resources were discovered for this connection.", code="no_resources")
        first = discovery.resources[0]
        return Resource(
            id=str(first["id"]),
            name=str(first["name"]),
            kind=str(first["kind"]),
            path=first.get("path"),
            size=first.get("size"),
            metadata=first.get("metadata") or {},
        )
    selector = str(selector)
    # A saved resource id/path wins; otherwise match a discovered name (common in the wizard).
    try:
        discovery = discover_connection(connection, request_id)
        for item in discovery.resources:
            if selector in {str(item.get("id")), str(item.get("path")), str(item.get("name"))}:
                return Resource(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    kind=str(item["kind"]),
                    path=item.get("path"),
                    size=item.get("size"),
                    metadata=item.get("metadata") or {},
                )
    except ConnectorError:
        pass
    return Resource(id=selector, name=selector.split("/")[-1], kind="file", path=selector)


def _store_raw(tenant_id: str, run_id: str, raw: RawAsset, index: int) -> str:
    key = f"{tenant_id}/raw/{run_id}/{index:03d}_{raw.filename}"
    get_storage().put_bytes(key, raw.content, raw.media_type)
    return key


def execute_ingestion(
    session: Session,
    ingestion: Ingestion,
    *,
    request_id: str,
    run_id: str,
    max_records: int | None = None,
) -> dict[str, Any]:
    connection = session.get(Connection, ingestion.connection_id)
    if not connection or connection.tenant_id != ingestion.tenant_id:
        raise ConnectorError("The source connection no longer exists.", code="connection_missing")
    connector = _connector(connection)
    context = _context(ingestion.tenant_id, request_id, run_id)
    secrets = collect_secrets(connection.config, connection.secret_ref)
    spec = ingestion.spec or {}
    options = dict(spec.get("options") or {})
    options.setdefault("limit", min(int(spec.get("limit", 100_000)), 1_000_000))
    resource = _select_resource(connection, spec, request_id, options)
    records: list[dict[str, Any]] = []
    parsed_assets: list[ParsedAsset] = []
    raw_keys: list[str] = []
    source_uris: list[str] = []
    documents = 0
    effective_limit = max_records or int(spec.get("max_records") or 200_000)
    file_index = 0
    for batch in connector.read(context, connection.config, secrets, resource, options):
        source_uris.append(batch.source_uri)
        if batch.raw is not None:
            raw_keys.append(_store_raw(ingestion.tenant_id, run_id, batch.raw, file_index))
            file_index += 1
            parsed = parse_asset(batch.raw, max_records=effective_limit)
            parsed_assets.append(parsed)
            records.extend(parsed.records)
            if parsed.kind == "document":
                documents += len(parsed.records)
        if batch.records:
            records.extend(batch.records)
        if len(records) >= effective_limit:
            records = records[:effective_limit]
            break
    if not records:
        raise ConnectorError(
            "The connector returned no records. Check the resource and parser configuration.",
            code="empty_result",
        )
    # Merge schemas from raw parses and direct record batches.
    from ..parsers import infer_schema

    schema = infer_schema(records)
    is_document = bool(parsed_assets) and all(asset.kind == "document" for asset in parsed_assets)
    source_uri = next((uri for uri in source_uris if uri), resource.id)
    classification = spec.get("classification") or None
    dataset = save_dataset(
        session,
        tenant_id=ingestion.tenant_id,
        name=ingestion.target_dataset,
        records=records,
        schema=schema,
        layer=str(spec.get("layer") or ("raw" if is_document else "bronze")),
        description=ingestion.description or f"Ingested from {connection.name}",
        classification=classification,
        source_connection_id=connection.id,
        source_uri=source_uri,
        run_id=run_id,
        request_id=request_id,
        owner=ingestion.owner,
        document=is_document,
        extra_meta={
            "source_resources": source_uris[:20],
            "raw_objects": raw_keys[:20],
            "connector_type": connection.type,
            "truncated": len(records) >= effective_limit,
        },
    )
    ingestion.last_run_id = run_id
    from ..context import utcnow

    ingestion.last_run_at = utcnow()
    session.add(ingestion)
    session.flush()
    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "dataset_version": dataset.version,
        "rows": len(records),
        "columns": len(schema),
        "bytes": dataset.size_bytes,
        "classification": dataset.classification,
        "documents": documents,
        "source_uri": source_uri,
        "raw_objects": raw_keys[:20],
        "request_id": request_id,
    }


def resolve_connector_config(connection: Connection, key: str) -> str | None:
    return secret_for(connection.config, collect_secrets(connection.config, connection.secret_ref), key)
