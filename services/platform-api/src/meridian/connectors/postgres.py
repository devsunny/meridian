from __future__ import annotations

import re
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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from ..secrets import secret_for
from .utils import json_safe

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")


@register
class PostgresConnector(Connector):
    type = "postgres"
    label = "PostgreSQL"
    category = "database"
    description = "Read tables, views or bounded custom SQL from PostgreSQL using a secret DSN."
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("dsn_ref", "DSN secret reference", "secret", True, "", "env:PG_DSN or aws-sm:arn"),
        ConfigField("schema", "Schema", "string", False, "public"),
        ConfigField("table", "Table / view", "string", False, "", "Optional. Leave blank to discover all."),
        ConfigField("query", "Custom read-only query", "textarea", False, "", "SELECT ... (LIMIT is enforced)"),
        ConfigField("limit", "Row limit", "integer", False, 100000),
    ]
    icon = "database"

    def _dsn(self, secrets: dict[str, str | None]) -> str:
        dsn = secret_for({}, secrets, "dsn")
        if not dsn:
            raise ConnectorError("A PostgreSQL DSN secret is required (field: dsn_ref).", code="missing_dsn")
        if dsn.startswith("postgres://"):
            dsn = dsn.replace("postgres://", "postgresql://", 1)
        if dsn.startswith("postgresql://"):
            dsn = dsn.replace("postgresql://", "postgresql+pg8000://", 1)
        return dsn

    def _engine(self, secrets: dict[str, str | None]) -> Engine:
        return create_engine(self._dsn(secrets), pool_pre_ping=True, pool_recycle=300)

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            engine = self._engine(secrets)
            with engine.connect() as connection:
                version = connection.execute(text("SHOW server_version")).scalar()
            return ConnectionTest(
                True,
                f"Connected to PostgreSQL {version}.",
                int((time.perf_counter() - started) * 1000),
                {"server_version": version},
            )
        except ConnectorError as exc:
            return ConnectionTest(False, str(exc), int((time.perf_counter() - started) * 1000), {"code": exc.code})
        except Exception as exc:  # noqa: BLE001
            return ConnectionTest(False, f"Connection failed: {_safe_db_error(exc)}", int((time.perf_counter() - started) * 1000))

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        engine = self._engine(secrets)
        schema = str(config.get("schema") or "public")
        with engine.connect() as connection:
            inspector = inspect(connection)
            resources: list[Resource] = []
            for table_name in inspector.get_table_names(schema=schema)[:500]:
                columns = inspector.get_columns(table_name, schema=schema)
                resources.append(
                    Resource(
                        id=f"{schema}.{table_name}",
                        name=table_name,
                        kind="table",
                        path=f"{schema}.{table_name}",
                        metadata={"columns": len(columns), "schema": schema},
                    )
                )
            for view_name in inspector.get_view_names(schema=schema)[:500]:
                resources.append(
                    Resource(
                        id=f"{schema}.{view_name}",
                        name=view_name,
                        kind="view",
                        path=f"{schema}.{view_name}",
                        metadata={"schema": schema},
                    )
                )
        return resources

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        limit = min(int((options or {}).get("limit", config.get("limit", 100_000))), 1_000_000)
        query = str(config.get("query") or "").strip()
        schema = str(config.get("schema") or "public")
        if query:
            if not re.match(r"(?is)^\s*(select|with)\b", query) or ";" in query:
                raise ConnectorError("Only a single SELECT/CTE statement is allowed.", code="unsafe_query")
            sql = text(f"SELECT * FROM ({query}) AS meridian_source LIMIT :limit")
        else:
            table = str(config.get("table") or resource.name)
            if not IDENTIFIER.match(schema) or not IDENTIFIER.match(table):
                raise ConnectorError("Invalid table identifier.", code="invalid_identifier")
            sql = text(f'SELECT * FROM "{schema}"."{table}" LIMIT :limit')
        engine = self._engine(secrets)
        with engine.connect() as connection:
            result = connection.execute(sql, {"limit": limit})
            rows = [dict(row._mapping) for row in result]
        records = [{key: json_safe(value) for key, value in row.items()} for row in rows]
        ctx.logger.info("postgres_read", extra={"rows": len(records), "resource": resource.id})
        yield RecordBatch(records=records, source_uri=resource.id)


def _safe_db_error(exc: Exception) -> str:
    message = str(exc)
    # Never surface a DSN or password in a connector result.
    message = re.sub(r"postgresql(?:\+\w+)?://[^\s]+", "postgresql://***", message)
    return message[:400]
