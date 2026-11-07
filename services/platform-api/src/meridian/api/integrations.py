from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..models import ExternalSystem
from ..schemas import IntegrationCreate, IntegrationUpdate
from ..secrets import resolve_secret
from ..security import Principal, require
from ..serializers import external_system
from .deps import client_ip, get_or_404

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("")
def list_integrations(
    principal: Principal = Depends(require("integrations:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(
            select(ExternalSystem)
            .where(ExternalSystem.tenant_id == principal.tenant_id)
            .order_by(ExternalSystem.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [external_system(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_integration(
    body: IntegrationCreate,
    request: Request,
    principal: Principal = Depends(require("integrations:write")),
    db: Session = Depends(get_session),
) -> dict:
    if not body.base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Base URL must use http or https.")
    existing = db.execute(
        select(ExternalSystem).where(
            ExternalSystem.tenant_id == principal.tenant_id, ExternalSystem.name == body.name
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An integration with this name already exists.")
    entity = ExternalSystem(
        tenant_id=principal.tenant_id,
        name=body.name,
        type=body.type,
        base_url=body.base_url.rstrip("/"),
        secret_ref=body.secret_ref,
        config=body.config,
        enabled=body.enabled,
    )
    db.add(entity)
    db.flush()
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="integration.created",
        resource_type="external_system",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"type": entity.type, "name": entity.name},
    )
    db.commit()
    return external_system(entity)


@router.patch("/{integration_id}")
def update_integration(
    integration_id: str,
    body: IntegrationUpdate,
    request: Request,
    principal: Principal = Depends(require("integrations:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, ExternalSystem, integration_id, principal.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "base_url" and value:
            value = value.rstrip("/")
        setattr(entity, key, value)
    entity.updated_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="integration.updated",
        resource_type="external_system",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"fields": sorted(changes)},
    )
    db.commit()
    return external_system(entity)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: str,
    request: Request,
    principal: Principal = Depends(require("integrations:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, ExternalSystem, integration_id, principal.tenant_id)
    db.delete(entity)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="integration.deleted",
        resource_type="external_system",
        resource_id=integration_id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()


@router.post("/{integration_id}/test")
def test_integration(
    integration_id: str,
    request: Request,
    principal: Principal = Depends(require("integrations:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, ExternalSystem, integration_id, principal.tenant_id)
    token = resolve_secret(entity.secret_ref)
    headers = {"X-Request-ID": request_id_var.get(), "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    config = entity.config or {}
    endpoints = {
        "airflow": "/api/v1/health",
        "dbt_cloud": f"/api/v2/accounts/{config.get('account_id', '')}",
        "fivetran": "/v1/connectors",
        "airbyte": "/api/v1/health",
    }
    url = entity.base_url + endpoints.get(entity.type, "")
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers)
        ok = response.status_code < 400
        result = {
            "ok": ok,
            "status": response.status_code,
            "message": "Integration reachable." if ok else f"Provider returned HTTP {response.status_code}.",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except httpx.HTTPError as exc:
        ok = False
        result = {
            "ok": False,
            "status": None,
            "message": f"Network error: {exc.__class__.__name__}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    entity.status = "healthy" if ok else "unreachable"
    entity.last_tested_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="integration.tested",
        resource_type="external_system",
        resource_id=entity.id,
        outcome="success" if ok else "failure",
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"message": result["message"]},
    )
    db.commit()
    return {**result, "request_id": request_id_var.get()}
