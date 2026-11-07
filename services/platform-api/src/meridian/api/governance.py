from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import verify_audit_chain, write_audit
from ..context import request_id_var
from ..db import get_session
from ..models import AccessGrant, AccessRequest, AuditEvent, Dataset
from ..schemas import AccessDecision, AccessRequestCreate
from ..security import Principal, require
from ..serializers import access_request, grant
from ..serializers import audit as serialize_audit
from .deps import client_ip, dataset_or_404, get_or_404

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/summary")
def governance_summary(
    principal: Principal = Depends(require("governance:read")), db: Session = Depends(get_session)
) -> dict:
    datasets = (
        db.execute(select(Dataset).where(Dataset.tenant_id == principal.tenant_id)).scalars().all()
    )
    requests = (
        db.execute(select(AccessRequest).where(AccessRequest.tenant_id == principal.tenant_id)).scalars().all()
    )
    grants = (
        db.execute(
            select(AccessGrant).where(
                AccessGrant.tenant_id == principal.tenant_id, AccessGrant.revoked_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    active_grants = [item for item in grants if not item.expires_at or item.expires_at > now]
    by_class: dict[str, int] = {}
    pii: list[dict] = []
    for dataset in datasets:
        by_class[dataset.classification] = by_class.get(dataset.classification, 0) + 1
        for column in dataset.schema_json or []:
            if column.get("pii"):
                pii.append(
                    {
                        "dataset_id": dataset.id,
                        "dataset": dataset.name,
                        "column": column["name"],
                        "kind": column.get("pii_kind"),
                        "classification": dataset.classification,
                        "owner": dataset.owner,
                    }
                )
    return {
        "datasets": len(datasets),
        "by_classification": by_class,
        "pii_columns": pii,
        "pending_access_requests": len([item for item in requests if item.status == "PENDING"]),
        "active_grants": len(active_grants),
        "audit_chain": verify_audit_chain(db, principal.tenant_id),
        "request_id": request_id_var.get(),
    }


@router.get("/access-requests")
def list_access_requests(
    request_status: str | None = Query(default=None, alias="status"),
    principal: Principal = Depends(require("governance:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    statement = select(AccessRequest).where(AccessRequest.tenant_id == principal.tenant_id)
    if request_status:
        statement = statement.where(AccessRequest.status == request_status.upper())
    rows = (
        db.execute(statement.order_by(AccessRequest.created_at.desc()).limit(200)).scalars().all()
    )
    datasets = {
        dataset.id: dataset
        for dataset in db.execute(select(Dataset).where(Dataset.tenant_id == principal.tenant_id))
        .scalars()
        .all()
    }
    result = []
    for row in rows:
        item = access_request(row)
        dataset = datasets.get(row.dataset_id)
        item["dataset"] = (
            {"id": dataset.id, "name": dataset.name, "classification": dataset.classification}
            if dataset
            else None
        )
        result.append(item)
    return result


@router.post("/access-requests", status_code=status.HTTP_201_CREATED)
def create_access_request(
    body: AccessRequestCreate,
    request: Request,
    principal: Principal = Depends(require("governance:read")),
    db: Session = Depends(get_session),
) -> dict:
    dataset = dataset_or_404(db, principal.tenant_id, body.dataset_id)
    existing = db.execute(
        select(AccessRequest).where(
            AccessRequest.tenant_id == principal.tenant_id,
            AccessRequest.requester_id == principal.id,
            AccessRequest.dataset_id == dataset.id,
            AccessRequest.status.in_(["PENDING", "APPROVED"]),
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An open request for this dataset already exists.")
    entity = AccessRequest(
        tenant_id=principal.tenant_id,
        requester_id=principal.id,
        requester_email=principal.email,
        dataset_id=dataset.id,
        action=body.action,
        purpose=body.purpose,
        duration_days=body.duration_days,
        status="PENDING",
        expires_at=datetime.now(UTC) + timedelta(days=body.duration_days),
    )
    db.add(entity)
    db.flush()
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="access.requested",
        resource_type="dataset",
        resource_id=dataset.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"request_id": entity.id, "purpose": body.purpose, "action": body.action},
    )
    db.commit()
    return access_request(entity)


@router.post("/access-requests/{request_id}/approve")
def approve_access_request(
    request_id: str,
    body: AccessDecision,
    request: Request,
    principal: Principal = Depends(require("governance:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, AccessRequest, request_id, principal.tenant_id)
    if entity.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Request is already {entity.status}.")
    dataset = dataset_or_404(db, principal.tenant_id, entity.dataset_id)
    entity.status = "APPROVED"
    entity.approver_id = principal.id
    entity.decision_reason = body.reason
    entity.decided_at = datetime.now(UTC)
    expires_at = datetime.now(UTC) + timedelta(days=entity.duration_days)
    entity.expires_at = expires_at
    grant_entity = AccessGrant(
        tenant_id=principal.tenant_id,
        principal_id=entity.requester_id,
        principal_email=entity.requester_email,
        dataset_id=dataset.id,
        action=entity.action,
        request_id_ref=entity.id,
        granted_by=principal.email,
        expires_at=expires_at,
    )
    db.add(grant_entity)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="access.approved",
        resource_type="dataset",
        resource_id=dataset.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={
            "access_request_id": entity.id,
            "grant_id": grant_entity.id,
            "requester": entity.requester_email,
            "expires_at": expires_at.isoformat(),
            "reason": body.reason,
        },
    )
    db.commit()
    return {"request": access_request(entity), "grant": grant(grant_entity)}


@router.post("/access-requests/{request_id}/deny")
def deny_access_request(
    request_id: str,
    body: AccessDecision,
    request: Request,
    principal: Principal = Depends(require("governance:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, AccessRequest, request_id, principal.tenant_id)
    if entity.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Request is already {entity.status}.")
    entity.status = "DENIED"
    entity.approver_id = principal.id
    entity.decision_reason = body.reason
    entity.decided_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="access.denied",
        resource_type="dataset",
        resource_id=entity.dataset_id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"access_request_id": entity.id, "reason": body.reason},
    )
    db.commit()
    return access_request(entity)


@router.get("/grants")
def list_grants(
    include_revoked: bool = False,
    principal: Principal = Depends(require("governance:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    statement = select(AccessGrant).where(AccessGrant.tenant_id == principal.tenant_id)
    if not include_revoked:
        statement = statement.where(AccessGrant.revoked_at.is_(None))
    rows = db.execute(statement.order_by(AccessGrant.created_at.desc()).limit(500)).scalars().all()
    return [grant(row) for row in rows]


@router.delete("/grants/{grant_id}", status_code=204)
def revoke_grant(
    grant_id: str,
    request: Request,
    principal: Principal = Depends(require("governance:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, AccessGrant, grant_id, principal.tenant_id)
    entity.revoked_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="access.revoked",
        resource_type="dataset",
        resource_id=entity.dataset_id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"grant_id": entity.id, "principal": entity.principal_email},
    )
    db.commit()


@router.get("/classifications")
def classifications(
    principal: Principal = Depends(require("governance:read")), db: Session = Depends(get_session)
) -> dict:
    datasets = (
        db.execute(select(Dataset).where(Dataset.tenant_id == principal.tenant_id)).scalars().all()
    )
    columns = []
    for dataset in datasets:
        for column in dataset.schema_json or []:
            if column.get("pii") or column.get("classification") in {"confidential", "restricted"}:
                columns.append(
                    {
                        "dataset_id": dataset.id,
                        "dataset": dataset.name,
                        "layer": dataset.layer,
                        "column": column["name"],
                        "type": column.get("type"),
                        "pii": bool(column.get("pii")),
                        "pii_kind": column.get("pii_kind"),
                        "classification": dataset.classification,
                        "owner": dataset.owner,
                    }
                )
    return {
        "columns": columns,
        "summary": {
            "classified_columns": len(columns),
            "pii_columns": len([column for column in columns if column["pii"]]),
        },
        "request_id": request_id_var.get(),
    }


@router.get("/audit")
def audit_log(
    action: str | None = None,
    q: str | None = None,
    limit: int = 200,
    principal: Principal = Depends(require("audit:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    statement = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id)
    if action:
        statement = statement.where(AuditEvent.action == action)
    if q:
        like = f"%{q}%"
        statement = statement.where(
            or_(
                AuditEvent.actor_email.ilike(like),
                AuditEvent.action.ilike(like),
                AuditEvent.resource_id.ilike(like),
                AuditEvent.request_id.ilike(like),
            )
        )
    rows = (
        db.execute(statement.order_by(AuditEvent.seq.desc()).limit(min(limit, 1000))).scalars().all()
    )
    return [serialize_audit(row) for row in rows]


@router.get("/audit/verify")
def verify_audit(
    principal: Principal = Depends(require("audit:read")), db: Session = Depends(get_session)
) -> dict:
    return {**verify_audit_chain(db, principal.tenant_id), "request_id": request_id_var.get()}


@router.get("/soc2")
def soc2(
    principal: Principal = Depends(require("audit:read")), db: Session = Depends(get_session)
) -> dict:
    chain = verify_audit_chain(db, principal.tenant_id)
    audit_count = (
        db.execute(
            select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id).order_by(AuditEvent.seq.desc()).limit(1)
        )
        .scalars()
        .first()
    )
    open_requests = db.execute(
        select(AccessRequest).where(
            AccessRequest.tenant_id == principal.tenant_id, AccessRequest.status == "PENDING"
        )
    ).scalars().all()
    controls = [
        {
            "id": "CC6.1",
            "name": "Logical access — least privilege",
            "status": "configured",
            "evidence": "Six platform roles, tenant-scoped queries, OPA adapter, server-side dataset access checks.",
        },
        {
            "id": "CC6.2",
            "name": "Access provisioning and revocation",
            "status": "configured",
            "evidence": "Approval workflow, expiring grants, revoke API, audit events.",
        },
        {
            "id": "CC7.1",
            "name": "Security event monitoring",
            "status": "configured",
            "evidence": "JSONL logs with request_id, Prometheus metrics, OTel traces, immutable audit chain.",
        },
        {
            "id": "CC7.2",
            "name": "Change management",
            "status": "configured",
            "evidence": "Immutable pipeline versions, audit log, GitOps manifests, CI required.",
        },
        {
            "id": "CC7.3",
            "name": "Data classification and handling",
            "status": "configured",
            "evidence": "Automatic PII detection, classification labels, restricted-data grants.",
        },
        {
            "id": "CC8.1",
            "name": "Change approval",
            "status": "partially_configured",
            "evidence": "Pipeline revisions are audited; production promotion gates must be enabled in CI.",
        },
    ]
    return {
        "framework": "SOC 2 Type II readiness mapping (not a certification)",
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_chain": chain,
        "latest_audit_seq": audit_count.seq if audit_count else 0,
        "open_access_requests": len(open_requests),
        "controls": controls,
        "retention": {"audit": "7 years", "runs": "24 months hot", "logs": "90 days hot"},
        "request_id": request_id_var.get(),
    }
