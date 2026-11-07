from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AccessGrant, Dataset, JobRun, Tenant, User
from ..security import Principal

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


def new_request_id_header(request: Request) -> str:
    from ..context import new_request_id

    incoming = request.headers.get("X-Request-ID")
    if incoming and REQUEST_ID_RE.match(incoming):
        return incoming
    return new_request_id()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:80]
    return request.client.host if request.client else ""


def get_or_404(session: Session, model: Any, object_id: str, tenant_id: str) -> Any:
    obj = session.get(model, object_id)
    if not obj or getattr(obj, "tenant_id", None) != tenant_id:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return obj


def dataset_or_404(session: Session, tenant_id: str, dataset_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset or dataset.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


def pipeline_or_404(session: Session, tenant_id: str, pipeline_id: str) -> Any:
    from ..models import Pipeline

    return get_or_404(session, Pipeline, pipeline_id, tenant_id)


def run_or_404(session: Session, tenant_id: str, run_id: str) -> JobRun:
    run = session.get(JobRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


def active_grant(session: Session, tenant_id: str, dataset_id: str, principal: Principal) -> bool:
    now = datetime.now(UTC)
    grant = session.execute(
        select(AccessGrant)
        .where(
            AccessGrant.tenant_id == tenant_id,
            AccessGrant.dataset_id == dataset_id,
            AccessGrant.principal_id == principal.id,
            AccessGrant.revoked_at.is_(None),
            (AccessGrant.expires_at.is_(None)) | (AccessGrant.expires_at > now),
        )
        .limit(1)
    ).scalar_one_or_none()
    return grant is not None


def can_read_data(session: Session, dataset: Dataset, principal: Principal) -> bool:
    """Defence in depth. UI hiding is never the control; row access is checked server-side."""
    if principal.role in {"admin", "steward", "engineer"}:
        if dataset.classification != "restricted" or principal.role == "admin":
            return True
        return active_grant(session, dataset.tenant_id, dataset.id, principal)
    if principal.role in {"auditor", "viewer"}:
        return False
    if dataset.classification == "restricted":
        return active_grant(session, dataset.tenant_id, dataset.id, principal)
    return True


def require_data_access(session: Session, dataset: Dataset, principal: Principal) -> None:
    if not can_read_data(session, dataset, principal):
        raise HTTPException(
            status_code=403,
            detail=(
                "This dataset requires a governed access grant. Submit an access request "
                "from the Governance workspace."
            ),
        )


def accessible_dataset_ids(session: Session, tenant_id: str, principal: Principal) -> list[str]:
    datasets = session.execute(select(Dataset).where(Dataset.tenant_id == tenant_id)).scalars().all()
    return [dataset.id for dataset in datasets if can_read_data(session, dataset, principal)]


def tenant_or_404(session: Session, tenant_id: str) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return tenant


def admin_count(session: Session, tenant_id: str) -> int:
    return len(
        session.execute(
            select(User).where(User.tenant_id == tenant_id, User.role == "admin", User.is_active.is_(True))
        )
        .scalars()
        .all()
    )


_ = (Tenant, User)
