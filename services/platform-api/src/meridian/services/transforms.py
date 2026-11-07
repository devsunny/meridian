from __future__ import annotations

import contextlib
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from edp_connector_sdk import ConnectorError
from sqlalchemy.orm import Session

from ..models import Dataset
from ..storage import get_storage
from .datasets import save_dataset

FORBIDDEN_SQL = re.compile(
    r"(?is)\b(insert|update|delete|drop|alter|create|copy|attach|detach|install|load|export|pragma|call|truncate)\b"
)


def _quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


@contextmanager
def materialized_dataset(dataset: Dataset) -> Iterator[Path]:
    """Return a local JSONL path, downloading from object storage when necessary."""
    if not dataset.location:
        raise ConnectorError("Dataset has no stored data.", code="dataset_empty")
    local = get_storage().local_path(dataset.location)
    if local is not None and local.exists():
        yield local
        return
    content = get_storage().get_bytes(dataset.location)
    with tempfile.TemporaryDirectory(prefix="meridian-") as temp_dir:
        path = Path(temp_dir) / "data.jsonl"
        path.write_bytes(content)
        yield path


def _connect():
    import duckdb

    return duckdb.connect(database=":memory:")


def _load_inputs(connection, datasets: list[tuple[str, Dataset]]) -> None:
    for index, (alias, dataset) in enumerate(datasets):
        with materialized_dataset(dataset) as path:
            safe_alias = _safe_alias(alias)
            connection.execute(
                f'CREATE TABLE "{safe_alias}" AS SELECT * FROM read_json_auto(\'{_quote_path(path)}\')'
            )
            if index == 0:
                connection.execute(f'CREATE VIEW input AS SELECT * FROM "{safe_alias}"')


def _safe_alias(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not safe or safe[0].isdigit():
        safe = f"t_{safe}"
    return safe[:60]


def transform_sql(
    session: Session,
    *,
    tenant_id: str,
    inputs: list[tuple[str, Dataset]],
    sql: str,
    target_name: str,
    layer: str,
    run_id: str,
    request_id: str,
    owner: str = "",
) -> tuple[Dataset, int]:
    if not sql.strip():
        raise ConnectorError("Transform SQL is empty.", code="empty_sql")
    if ";" in sql:
        raise ConnectorError("Only one statement is allowed.", code="unsafe_sql")
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise ConnectorError("Transform must be a SELECT or WITH query.", code="unsafe_sql")
    if FORBIDDEN_SQL.search(sql):
        raise ConnectorError("Transform contains a disallowed statement.", code="unsafe_sql")
    connection = _connect()
    try:
        _load_inputs(connection, inputs)
        # The query can only see registered tables; disable external file/network access.
        with contextlib.suppress(Exception):
            connection.execute("SET enable_external_access=false")
        cursor = connection.execute(sql)
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchall()
        records = [
            {column: (str(value) if hasattr(value, "isoformat") else value) for column, value in zip(columns, row, strict=False)}
            for row in rows
        ]
    finally:
        connection.close()
    from ..parsers import infer_schema

    schema = infer_schema(records)
    dataset = save_dataset(
        session,
        tenant_id=tenant_id,
        name=target_name,
        records=records,
        schema=schema,
        layer=layer,
        description=f"SQL transform produced by run {run_id}",
        run_id=run_id,
        request_id=request_id,
        owner=owner,
        extra_meta={"sql": sql[:4000], "inputs": [dataset.id for _, dataset in inputs]},
    )
    return dataset, len(records)


def query_dataset(dataset: Dataset, sql: str, limit: int = 100) -> tuple[list[str], list[dict[str, Any]]]:
    if ";" in sql or not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise ConnectorError("Only a single SELECT/CTE query is allowed.", code="unsafe_sql")
    if FORBIDDEN_SQL.search(sql):
        raise ConnectorError("Query contains a disallowed statement.", code="unsafe_sql")
    connection = _connect()
    try:
        with materialized_dataset(dataset) as path:
            connection.execute(f'CREATE TABLE input AS SELECT * FROM read_json_auto(\'{_quote_path(path)}\')')
        with contextlib.suppress(Exception):
            connection.execute("SET enable_external_access=false")
        cursor = connection.execute(f"SELECT * FROM ({sql}) AS meridian_query LIMIT {int(limit)}")
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchall()
        return columns, [
            {
                column: (value.isoformat() if hasattr(value, "isoformat") else value)
                for column, value in zip(columns, row, strict=False)
            }
            for row in rows
        ]
    finally:
        connection.close()


def run_quality_checks(
    dataset: Dataset,
    *,
    min_rows: int = 1,
    required_columns: list[str] | None = None,
    max_null_pct: float | None = None,
    unique_column: str | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    checks: list[dict[str, Any]] = []
    if dataset.row_count < min_rows:
        failures.append(f"row_count {dataset.row_count} is below minimum {min_rows}")
    checks.append({"check": "min_rows", "passed": dataset.row_count >= min_rows, "observed": dataset.row_count})
    columns = {column["name"] for column in dataset.schema_json or []}
    for column in required_columns or []:
        ok = column in columns
        checks.append({"check": f"required_column:{column}", "passed": ok})
        if not ok:
            failures.append(f"missing required column '{column}'")
    if max_null_pct is not None:
        for name, profile in (dataset.profile or {}).get("columns", {}).items():
            null_pct = float(profile.get("null_pct", 0))
            ok = null_pct <= max_null_pct
            checks.append({"check": f"null_pct:{name}", "passed": ok, "observed": null_pct})
            if not ok:
                failures.append(f"column '{name}' null_pct {null_pct} exceeds {max_null_pct}")
    if unique_column:
        from .datasets import preview_dataset

        rows = preview_dataset(dataset, limit=10_000)
        values = [row.get(unique_column) for row in rows]
        non_null = [value for value in values if value is not None]
        ok = len(non_null) == len(set(map(str, non_null)))
        checks.append({"check": f"unique:{unique_column}", "passed": ok, "observed": len(non_null)})
        if not ok:
            failures.append(f"column '{unique_column}' is not unique in the sampled rows")
    return {"passed": not failures, "checks": checks, "failures": failures}
