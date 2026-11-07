from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..engine.dag import create_ingestion_run, next_run_time
from ..models import Connection, Ingestion, JobRun, Schedule
from ..schemas import IngestionCreate, IngestionUpdate, RunCreate
from ..security import Principal, require
from ..serializers import ingestion, run
from .deps import client_ip, get_or_404

router = APIRouter(tags=["ingestions"])


def _validate_cron(cron: str | None, timezone: str) -> None:
    if not cron:
        return
    from zoneinfo import ZoneInfo

    from croniter import croniter

    if not croniter.is_valid(cron):
        raise HTTPException(status_code=422, detail="Invalid cron expression.")
    try:
        ZoneInfo(timezone)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Invalid timezone.") from exc


@router.get("/ingestions")
def list_ingestions(
    principal: Principal = Depends(require("ingestions:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(
            select(Ingestion)
            .where(Ingestion.tenant_id == principal.tenant_id, Ingestion.status != "archived")
            .order_by(Ingestion.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [ingestion(row) for row in rows]


@router.post("/ingestions", status_code=status.HTTP_201_CREATED)
def create_ingestion(
    body: IngestionCreate,
    request: Request,
    principal: Principal = Depends(require("ingestions:write")),
    db: Session = Depends(get_session),
) -> dict:
    connection = get_or_404(db, Connection, body.connection_id, principal.tenant_id)
    if connection.status != "active":
        raise HTTPException(status_code=409, detail="Source is not active.")
    _validate_cron(body.schedule_cron, body.schedule_timezone)
    existing = db.execute(
        select(Ingestion).where(Ingestion.tenant_id == principal.tenant_id, Ingestion.name == body.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An ingestion with this name already exists.")
    entity = Ingestion(
        tenant_id=principal.tenant_id,
        name=body.name,
        description=body.description,
        connection_id=connection.id,
        target_dataset=body.target_dataset,
        spec=body.spec,
        schedule_cron=body.schedule_cron,
        schedule_timezone=body.schedule_timezone,
        owner=body.owner or principal.email,
    )
    db.add(entity)
    db.flush()
    if body.schedule_cron:
        db.add(
            Schedule(
                tenant_id=principal.tenant_id,
                name=f"{body.name} schedule",
                target_type="ingestion",
                target_id=entity.id,
                cron=body.schedule_cron,
                timezone=body.schedule_timezone,
                next_run_at=next_run_time(body.schedule_cron, body.schedule_timezone, datetime.now(UTC)),
            )
        )
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="ingestion.created",
        resource_type="ingestion",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"connection_id": connection.id, "target_dataset": entity.target_dataset},
    )
    db.commit()
    return ingestion(entity)


@router.get("/ingestions/{ingestion_id}")
def get_ingestion(
    ingestion_id: str,
    principal: Principal = Depends(require("ingestions:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Ingestion, ingestion_id, principal.tenant_id)
    payload = ingestion(entity)
    connection = db.get(Connection, entity.connection_id)
    payload["connection"] = {"id": connection.id, "name": connection.name, "type": connection.type} if connection else None
    return payload


@router.patch("/ingestions/{ingestion_id}")
def update_ingestion(
    ingestion_id: str,
    body: IngestionUpdate,
    request: Request,
    principal: Principal = Depends(require("ingestions:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Ingestion, ingestion_id, principal.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    if "schedule_cron" in changes:
        _validate_cron(changes.get("schedule_cron"), changes.get("schedule_timezone") or entity.schedule_timezone)
    for key, value in changes.items():
        setattr(entity, key, value)
    entity.updated_at = datetime.now(UTC)
    if "schedule_cron" in changes and entity.schedule_cron:
        schedules = (
            db.execute(
                select(Schedule).where(
                    Schedule.tenant_id == principal.tenant_id,
                    Schedule.target_type == "ingestion",
                    Schedule.target_id == entity.id,
                )
            )
            .scalars()
            .all()
        )
        for schedule in schedules:
            schedule.cron = entity.schedule_cron
            schedule.timezone = entity.schedule_timezone
            schedule.next_run_at = next_run_time(schedule.cron, schedule.timezone, datetime.now(UTC))
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="ingestion.updated",
        resource_type="ingestion",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"fields": sorted(changes)},
    )
    db.commit()
    return ingestion(entity)


@router.delete("/ingestions/{ingestion_id}", status_code=204)
def archive_ingestion(
    ingestion_id: str,
    request: Request,
    principal: Principal = Depends(require("ingestions:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, Ingestion, ingestion_id, principal.tenant_id)
    entity.status = "archived"
    for schedule in (
        db.execute(
            select(Schedule).where(
                Schedule.tenant_id == principal.tenant_id,
                Schedule.target_type == "ingestion",
                Schedule.target_id == entity.id,
            )
        )
        .scalars()
        .all()
    ):
        schedule.enabled = False
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="ingestion.archived",
        resource_type="ingestion",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()


@router.post("/ingestions/{ingestion_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_ingestion(
    ingestion_id: str,
    body: RunCreate,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Ingestion, ingestion_id, principal.tenant_id)
    if entity.status != "active":
        raise HTTPException(status_code=409, detail="Ingestion is not active.")
    active = db.execute(
        select(JobRun).where(
            JobRun.tenant_id == principal.tenant_id,
            JobRun.target_id == entity.id,
            JobRun.status.in_(["QUEUED", "RUNNING", "PAUSED"]),
        )
    ).scalars().first()
    if active and not body.force:
        raise HTTPException(status_code=409, detail=f"Ingestion already has active run {active.id}.")
    job = create_ingestion_run(
        db,
        entity,
        request_id=request_id_var.get(),
        created_by=principal.email,
        trigger="manual",
        logical_date=body.logical_date,
    )
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.started",
        resource_type="ingestion_run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"ingestion_id": entity.id, "request_id": job.request_id},
    )
    db.commit()
    return run(job)


@router.get("/ingestions/{ingestion_id}/runs")
def ingestion_runs(
    ingestion_id: str,
    limit: int = 25,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    entity = get_or_404(db, Ingestion, ingestion_id, principal.tenant_id)
    rows = (
        db.execute(
            select(JobRun)
            .where(JobRun.tenant_id == principal.tenant_id, JobRun.target_id == entity.id, JobRun.kind == "ingestion")
            .order_by(JobRun.created_at.desc())
            .limit(min(limit, 100))
        )
        .scalars()
        .all()
    )
    return [run(row) for row in rows]
