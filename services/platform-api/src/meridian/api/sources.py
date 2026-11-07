from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..context import new_id, request_id_var
from ..db import get_session
from ..models import Connection, Ingestion, Upload
from ..schemas import ConnectionCreate, ConnectionUpdate
from ..security import Principal, require
from ..serializers import connection
from ..services.ingestion import connector_catalog, discover_connection, test_connection
from .deps import client_ip, get_or_404

router = APIRouter(tags=["sources"])
settings = get_settings()
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@router.get("/connectors")
def list_connectors(principal: Principal = Depends(require("sources:read"))) -> list[dict]:
    return connector_catalog()


@router.get("/connections")
def list_connections(
    principal: Principal = Depends(require("sources:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(
            select(Connection)
            .where(Connection.tenant_id == principal.tenant_id, Connection.status != "archived")
            .order_by(Connection.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [connection(row) for row in rows]


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def create_connection(
    body: ConnectionCreate,
    request: Request,
    principal: Principal = Depends(require("sources:write")),
    db: Session = Depends(get_session),
) -> dict:
    catalog = {item["type"] for item in connector_catalog()}
    if body.type not in catalog:
        raise HTTPException(status_code=422, detail=f"Unknown connector type '{body.type}'.")
    existing = db.execute(
        select(Connection).where(Connection.tenant_id == principal.tenant_id, Connection.name == body.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A source with this name already exists.")
    entity = Connection(
        tenant_id=principal.tenant_id,
        name=body.name,
        type=body.type,
        description=body.description,
        config=body.config,
        secret_ref=body.secret_ref,
        owner=principal.email,
    )
    db.add(entity)
    db.flush()
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="source.created",
        resource_type="connection",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"type": body.type, "name": body.name},
    )
    db.commit()
    return connection(entity)


@router.get("/connections/{connection_id}")
def get_connection(
    connection_id: str,
    principal: Principal = Depends(require("sources:read")),
    db: Session = Depends(get_session),
) -> dict:
    return connection(get_or_404(db, Connection, connection_id, principal.tenant_id))


@router.patch("/connections/{connection_id}")
def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    request: Request,
    principal: Principal = Depends(require("sources:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Connection, connection_id, principal.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(entity, key, value)
    entity.updated_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="source.updated",
        resource_type="connection",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"fields": sorted(changes)},
    )
    db.commit()
    return connection(entity)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(
    connection_id: str,
    request: Request,
    principal: Principal = Depends(require("sources:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, Connection, connection_id, principal.tenant_id)
    used = db.execute(
        select(func.count())
        .select_from(Ingestion)
        .where(Ingestion.tenant_id == principal.tenant_id, Ingestion.connection_id == entity.id)
    ).scalar()
    if used:
        raise HTTPException(status_code=409, detail="Source is referenced by an ingestion. Archive it instead.")
    entity.status = "archived"
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="source.archived",
        resource_type="connection",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()


@router.post("/connections/{connection_id}/test")
def test_source(
    connection_id: str,
    request: Request,
    principal: Principal = Depends(require("sources:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Connection, connection_id, principal.tenant_id)
    result = test_connection(entity, request_id_var.get())
    entity.last_tested_at = datetime.now(UTC)
    entity.last_test_ok = bool(result.get("ok"))
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="source.tested",
        resource_type="connection",
        resource_id=entity.id,
        outcome="success" if result.get("ok") else "failure",
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"message": result.get("message"), "latency_ms": result.get("latency_ms")},
    )
    db.commit()
    return {**result, "request_id": request_id_var.get()}


@router.post("/connections/{connection_id}/discover")
def discover_source(
    connection_id: str,
    principal: Principal = Depends(require("sources:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Connection, connection_id, principal.tenant_id)
    result = discover_connection(entity, request_id_var.get())
    return {
        "resources": result.resources,
        "connector": result.connector,
        "request_id": request_id_var.get(),
    }


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require("sources:write")),
    db: Session = Depends(get_session),
) -> dict:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 100 MB upload limit.")
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    filename = Path(file.filename or "upload.bin").name
    upload_id = new_id("upl")
    base = Path(settings.storage_root).expanduser().resolve().parent / "uploads" / principal.tenant_id / upload_id
    base.mkdir(parents=True, exist_ok=True)
    path = base / filename
    path.write_bytes(content)
    upload = Upload(
        id=upload_id,
        tenant_id=principal.tenant_id,
        filename=filename,
        path=str(path),
        size=len(content),
        media_type=file.content_type or "application/octet-stream",
        sha256=hashlib.sha256(content).hexdigest(),
        created_by=principal.email,
    )
    db.add(upload)
    connection_entity = Connection(
        tenant_id=principal.tenant_id,
        name=f"Upload · {filename} · {upload_id[-6:]}",
        type="file",
        description="File uploaded through the Meridian console.",
        config={"path": str(path), "root": str(path.parent), "upload": True},
        owner=principal.email,
    )
    db.add(connection_entity)
    db.flush()
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="file.uploaded",
        resource_type="upload",
        resource_id=upload.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"filename": filename, "size": len(content), "sha256": upload.sha256, "connection_id": connection_entity.id},
    )
    db.commit()
    return {
        "upload_id": upload.id,
        "filename": filename,
        "size": len(content),
        "sha256": upload.sha256,
        "connection": connection(connection_entity),
        "resource": {
            "id": str(path),
            "name": filename,
            "path": str(path),
            "kind": "file",
            "size": len(content),
        },
        "request_id": request_id_var.get(),
    }
