from __future__ import annotations

from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..models import Dataset, LineageEdge
from ..schemas import QueryRequest
from ..security import Principal, require
from ..serializers import dataset as serialize_dataset
from ..services.datasets import dataset_list_item, preview_dataset
from ..services.transforms import query_dataset
from ..storage import get_storage
from .deps import can_read_data, client_ip, dataset_or_404, require_data_access

router = APIRouter(tags=["catalog"])


@router.get("/datasets")
def list_datasets(
    layer: str | None = None,
    classification: str | None = None,
    q: str | None = None,
    limit: int = 200,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    statement = select(Dataset).where(Dataset.tenant_id == principal.tenant_id)
    if layer:
        statement = statement.where(Dataset.layer == layer)
    if classification:
        statement = statement.where(Dataset.classification == classification)
    if q:
        like = f"%{q.lower()}%"
        statement = statement.where(
            or_(Dataset.name.ilike(like), Dataset.description.ilike(like), Dataset.owner.ilike(like))
        )
    rows = (
        db.execute(statement.order_by(Dataset.updated_at.desc()).limit(min(limit, 500))).scalars().all()
    )
    result = []
    for row in rows:
        item = dataset_list_item(row)
        item["can_read"] = can_read_data(db, row, principal)
        result.append(item)
    return result


@router.get("/catalog/search")
def search(
    q: str = Query(min_length=1),
    limit: int = 50,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    like = f"%{q.lower()}%"
    rows = (
        db.execute(
            select(Dataset)
            .where(
                Dataset.tenant_id == principal.tenant_id,
                or_(
                    Dataset.name.ilike(like),
                    Dataset.description.ilike(like),
                    Dataset.owner.ilike(like),
                    Dataset.source_uri.ilike(like),
                ),
            )
            .order_by(Dataset.updated_at.desc())
            .limit(min(limit, 100))
        )
        .scalars()
        .all()
    )
    return {
        "query": q,
        "results": [dataset_list_item(row) for row in rows],
        "request_id": request_id_var.get(),
    }


@router.get("/catalog/stats")
def catalog_stats(
    principal: Principal = Depends(require("catalog:read")), db: Session = Depends(get_session)
) -> dict:
    rows = (
        db.execute(select(Dataset).where(Dataset.tenant_id == principal.tenant_id)).scalars().all()
    )
    by_layer: dict[str, int] = {}
    by_classification: dict[str, int] = {}
    pii_columns = 0
    for row in rows:
        by_layer[row.layer] = by_layer.get(row.layer, 0) + 1
        by_classification[row.classification] = by_classification.get(row.classification, 0) + 1
        pii_columns += len([column for column in (row.schema_json or []) if column.get("pii")])
    return {
        "datasets": len(rows),
        "rows": sum(row.row_count for row in rows),
        "bytes": sum(row.size_bytes for row in rows),
        "pii_columns": pii_columns,
        "by_layer": by_layer,
        "by_classification": by_classification,
        "request_id": request_id_var.get(),
    }


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: str,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    payload = serialize_dataset(entity)
    payload["can_read"] = can_read_data(db, entity, principal)
    payload["lineage"] = _lineage_graph(db, principal.tenant_id, entity.id, depth=2)
    return payload


@router.get("/datasets/{dataset_id}/preview")
def preview(
    dataset_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    require_data_access(db, entity, principal)
    rows = preview_dataset(entity, limit=min(limit, 500), offset=max(offset, 0))
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="data.previewed",
        resource_type="dataset",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"limit": limit, "offset": offset, "classification": entity.classification},
    )
    db.commit()
    return {
        "dataset_id": entity.id,
        "columns": [column["name"] for column in entity.schema_json or []],
        "rows": rows,
        "limit": limit,
        "offset": offset,
        "classification": entity.classification,
        "request_id": request_id_var.get(),
    }


@router.get("/datasets/{dataset_id}/profile")
def profile(
    dataset_id: str,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    return {
        "dataset_id": entity.id,
        "row_count": entity.row_count,
        "version": entity.version,
        "schema": entity.schema_json or [],
        "profile": entity.profile or {},
        "classification": entity.classification,
        "request_id": request_id_var.get(),
    }


@router.get("/datasets/{dataset_id}/lineage")
def lineage(
    dataset_id: str,
    depth: int = 3,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    return {
        **_lineage_graph(db, principal.tenant_id, entity.id, depth=min(depth, 5)),
        "request_id": request_id_var.get(),
    }


@router.post("/datasets/{dataset_id}/query")
def query(
    dataset_id: str,
    body: QueryRequest,
    request: Request,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    require_data_access(db, entity, principal)
    try:
        columns, rows = query_dataset(entity, body.sql, limit=min(body.limit, 1000))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Query failed: {exc}") from exc
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="data.queried",
        resource_type="dataset",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"rows": len(rows), "sql": body.sql[:1000]},
    )
    db.commit()
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "request_id": request_id_var.get(),
    }


@router.get("/datasets/{dataset_id}/download")
def download(
    dataset_id: str,
    request: Request,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> Response:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    require_data_access(db, entity, principal)
    if not entity.location:
        raise HTTPException(status_code=404, detail="Dataset has no stored object.")
    content = get_storage().get_bytes(entity.location)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="data.downloaded",
        resource_type="dataset",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"bytes": len(content), "classification": entity.classification},
    )
    db.commit()
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{entity.name}.jsonl"',
            "X-Request-ID": request_id_var.get(),
        },
    )


@router.get("/datasets/{dataset_id}/access")
def access(
    dataset_id: str,
    principal: Principal = Depends(require("catalog:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = dataset_or_404(db, principal.tenant_id, dataset_id)
    return {
        "can_read": can_read_data(db, entity, principal),
        "classification": entity.classification,
        "pii_columns": [column["name"] for column in (entity.schema_json or []) if column.get("pii")],
        "request_id": request_id_var.get(),
    }


def _lineage_graph(db: Session, tenant_id: str, dataset_id: str, depth: int = 3) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(dataset_id, 0)])
    visited = {dataset_id}
    while queue:
        current, distance = queue.popleft()
        entity = db.get(Dataset, current)
        if entity and entity.tenant_id == tenant_id:
            nodes[current] = {
                "id": entity.id,
                "name": entity.name,
                "layer": entity.layer,
                "classification": entity.classification,
                "row_count": entity.row_count,
                "is_root": current == dataset_id,
            }
        if distance >= depth:
            continue
        rows = (
            db.execute(
                select(LineageEdge).where(
                    LineageEdge.tenant_id == tenant_id,
                    or_(LineageEdge.from_dataset_id == current, LineageEdge.to_dataset_id == current),
                )
            )
            .scalars()
            .all()
        )
        for edge in rows:
            if edge.id not in seen_edges:
                seen_edges.add(edge.id)
                edges.append(
                    {
                        "id": edge.id,
                        "source": edge.from_dataset_id,
                        "target": edge.to_dataset_id,
                        "operation": edge.operation,
                        "run_id": edge.job_run_id,
                    }
                )
            for neighbour in (edge.from_dataset_id, edge.to_dataset_id):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, distance + 1))
    for edge in edges:
        for key in (edge["source"], edge["target"]):
            if key not in nodes:
                entity = db.get(Dataset, key)
                if entity and entity.tenant_id == tenant_id:
                    nodes[key] = {
                        "id": entity.id,
                        "name": entity.name,
                        "layer": entity.layer,
                        "classification": entity.classification,
                        "row_count": entity.row_count,
                        "is_root": key == dataset_id,
                    }
    return {
        "root": dataset_id,
        "nodes": list(nodes.values()),
        "edges": [edge for edge in edges if edge["source"] in nodes and edge["target"] in nodes],
    }


_ = (func, status)
