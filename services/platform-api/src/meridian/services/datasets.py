from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..context import new_id, request_id_var
from ..logging_setup import get_logger
from ..models import Dataset, DatasetVersion, DocumentChunk, LineageEdge, Tenant
from ..parsers import classification_for, profile_records
from ..serializers import dt
from ..storage import dataset_key, get_storage

logger = get_logger("meridian.datasets")


def save_dataset(
    session: Session,
    *,
    tenant_id: str,
    name: str,
    records: list[dict[str, Any]],
    schema: list[dict[str, Any]],
    layer: str = "raw",
    description: str = "",
    classification: str | None = None,
    source_connection_id: str | None = None,
    source_uri: str = "",
    run_id: str | None = None,
    request_id: str | None = None,
    owner: str = "",
    document: bool = False,
    extra_meta: dict[str, Any] | None = None,
) -> Dataset:
    storage = get_storage()
    dataset = session.execute(
        select(Dataset).where(Dataset.tenant_id == tenant_id, Dataset.name == name)
    ).scalar_one_or_none()
    version = (dataset.version if dataset else 0) + 1
    if dataset is None:
        dataset = Dataset(
            id=new_id("ds"),
            tenant_id=tenant_id,
            name=name,
            description=description,
            layer=layer,
            owner=owner,
            version=0,
        )
        session.add(dataset)
        session.flush()
    key = dataset_key(tenant_id, dataset.id, version)
    storage.put_jsonl(key, records)
    size = storage.size(key)
    resolved_classification = classification_for(schema, classification)
    profile = profile_records(records, schema)
    profile["pii_columns"] = [column["name"] for column in schema if column.get("pii")]
    profile["document"] = document
    if extra_meta:
        profile.update(extra_meta)
    dataset.description = description or dataset.description
    dataset.layer = layer
    dataset.format = "jsonl"
    dataset.classification = resolved_classification
    dataset.location = key
    dataset.row_count = len(records)
    dataset.size_bytes = size
    dataset.version = version
    dataset.schema_json = schema
    dataset.profile = profile
    dataset.source_connection_id = source_connection_id or dataset.source_connection_id
    dataset.source_uri = source_uri or dataset.source_uri
    dataset.owner = owner or dataset.owner
    dataset.updated_at = datetime.now(UTC)
    session.add(dataset)
    session.flush()
    session.add(
        DatasetVersion(
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            version=version,
            location=key,
            row_count=len(records),
            size_bytes=size,
            schema_json=schema,
            run_id=run_id,
            request_id=request_id or request_id_var.get(),
        )
    )
    if document:
        _replace_chunks(
            session,
            tenant_id=tenant_id,
            dataset=dataset,
            records=records,
            classification=resolved_classification,
            source_uri=source_uri,
        )
    session.flush()
    logger.info(
        "dataset_landed",
        extra={
            "dataset_id": dataset.id,
            "dataset": dataset.name,
            "version": version,
            "rows": len(records),
            "size_bytes": size,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "request_id": request_id or request_id_var.get(),
        },
    )
    return dataset


def _replace_chunks(
    session: Session,
    *,
    tenant_id: str,
    dataset: Dataset,
    records: list[dict[str, Any]],
    classification: str,
    source_uri: str,
) -> None:
    # Document chunks are the retrieval unit for governed RAG. Replace on re-ingest.
    existing = (
        session.execute(select(DocumentChunk).where(DocumentChunk.dataset_id == dataset.id)).scalars().all()
    )
    for chunk in existing:
        session.delete(chunk)
    session.flush()
    for record in records[:20_000]:
        text = str(record.get("text") or "").strip()
        if not text:
            continue
        session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                dataset_id=dataset.id,
                source_uri=str(record.get("source_uri") or source_uri),
                filename=str(record.get("filename") or ""),
                page=int(record["page"]) if record.get("page") not in (None, "") else None,
                chunk_index=int(record.get("chunk_index") or 0),
                text=text,
                token_count=max(1, len(text) // 4),
                classification=classification,
                meta={"doc_id": record.get("doc_id")},
            )
        )


def add_lineage(
    session: Session,
    *,
    tenant_id: str,
    from_dataset_id: str,
    to_dataset_id: str,
    run_id: str | None,
    task_id: str | None,
    operation: str,
    request_id: str,
) -> None:
    if from_dataset_id == to_dataset_id:
        return
    exists = session.execute(
        select(LineageEdge).where(
            LineageEdge.tenant_id == tenant_id,
            LineageEdge.from_dataset_id == from_dataset_id,
            LineageEdge.to_dataset_id == to_dataset_id,
            LineageEdge.job_run_id == run_id,
        )
    ).scalar_one_or_none()
    if exists:
        return
    session.add(
        LineageEdge(
            tenant_id=tenant_id,
            from_dataset_id=from_dataset_id,
            to_dataset_id=to_dataset_id,
            job_run_id=run_id,
            task_id=task_id,
            operation=operation,
            request_id=request_id,
        )
    )


def dataset_list_item(dataset: Dataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "layer": dataset.layer,
        "format": dataset.format,
        "classification": dataset.classification,
        "owner": dataset.owner,
        "row_count": dataset.row_count,
        "size_bytes": dataset.size_bytes,
        "version": dataset.version,
        "columns": len(dataset.schema_json or []),
        "pii_columns": [c["name"] for c in (dataset.schema_json or []) if c.get("pii")],
        "source_uri": dataset.source_uri,
        "updated_at": dt(dataset.updated_at),
        "created_at": dt(dataset.created_at),
    }


def dataset_detail(dataset: Dataset) -> dict[str, Any]:
    data = dataset_list_item(dataset)
    data.update(
        {
            "schema": dataset.schema_json or [],
            "profile": dataset.profile or {},
            "location": dataset.location,
            "source_connection_id": dataset.source_connection_id,
        }
    )
    return data


def preview_dataset(dataset: Dataset, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    if not dataset.location:
        return []
    return get_storage().read_jsonl(dataset.location, limit=limit, offset=offset)


def iter_dataset(dataset: Dataset) -> Iterable[dict[str, Any]]:
    if not dataset.location:
        return iter(())
    return get_storage().iter_jsonl(dataset.location)


def search_catalog(
    session: Session, tenant_id: str, query: str, limit: int = 50
) -> list[dict[str, Any]]:
    statement = select(Dataset).where(Dataset.tenant_id == tenant_id)
    if query:
        like = f"%{query.lower()}%"
        statement = statement.where(
            Dataset.name.ilike(like)
            | Dataset.description.ilike(like)
            | Dataset.owner.ilike(like)
            | Dataset.source_uri.ilike(like)
        )
    datasets = session.execute(statement.order_by(Dataset.updated_at.desc()).limit(limit)).scalars().all()
    return [dataset_list_item(dataset) for dataset in datasets]


def hash_records(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records[:10_000]:
        digest.update(str(sorted(record.items())).encode())
    return digest.hexdigest()


def tenant_dashboard(session: Session, tenant_id: str) -> dict[str, Any]:
    from sqlalchemy import func

    from ..models import Connection, Ingestion, JobRun, Pipeline, Schedule

    def count(model: Any) -> int:
        return int(
            session.execute(select(func.count()).select_from(model).where(model.tenant_id == tenant_id)).scalar()
            or 0
        )

    runs = (
        session.execute(
            select(JobRun)
            .where(JobRun.tenant_id == tenant_id)
            .order_by(JobRun.created_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )
    running = (
        session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.tenant_id == tenant_id, JobRun.status.in_(["QUEUED", "RUNNING", "PAUSED"]))
        ).scalar()
        or 0
    )
    succeeded = (
        session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.tenant_id == tenant_id, JobRun.status == "SUCCEEDED")
        ).scalar()
        or 0
    )
    failed = (
        session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.tenant_id == tenant_id, JobRun.status == "FAILED")
        ).scalar()
        or 0
    )
    storage_bytes = (
        session.execute(
            select(func.coalesce(func.sum(Dataset.size_bytes), 0)).where(Dataset.tenant_id == tenant_id)
        ).scalar()
        or 0
    )
    rows = (
        session.execute(
            select(func.coalesce(func.sum(Dataset.row_count), 0)).where(Dataset.tenant_id == tenant_id)
        ).scalar()
        or 0
    )
    schedules = (
        session.execute(
            select(Schedule)
            .where(Schedule.tenant_id == tenant_id, Schedule.enabled.is_(True))
            .order_by(Schedule.next_run_at.asc())
            .limit(5)
        )
        .scalars()
        .all()
    )
    tenant = session.get(Tenant, tenant_id)
    total_runs = succeeded + failed
    return {
        "tenant": {"id": tenant_id, "slug": tenant.slug if tenant else "", "name": tenant.name if tenant else ""},
        "counts": {
            "connections": count(Connection),
            "ingestions": count(Ingestion),
            "pipelines": count(Pipeline),
            "datasets": count(Dataset),
            "schedules": count(Schedule),
            "active_runs": int(running),
            "storage_bytes": int(storage_bytes),
            "rows": int(rows),
            "success_rate": round(succeeded / total_runs * 100, 1) if total_runs else 100.0,
        },
        "recent_runs": [
            {
                "id": run.id,
                "kind": run.kind,
                "target_id": run.target_id,
                "status": run.status,
                "trigger": run.trigger,
                "created_at": dt(run.created_at),
                "request_id": run.request_id,
            }
            for run in runs
        ],
        "upcoming_schedules": [
            {
                "id": schedule.id,
                "name": schedule.name,
                "cron": schedule.cron,
                "next_run_at": dt(schedule.next_run_at),
                "target_type": schedule.target_type,
            }
            for schedule in schedules
        ],
    }
