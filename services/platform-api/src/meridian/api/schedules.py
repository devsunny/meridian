from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..engine.dag import next_run_time, schedule_run
from ..models import Ingestion, Pipeline, Schedule
from ..schemas import ScheduleCreate, ScheduleUpdate
from ..security import Principal, require
from ..serializers import run, schedule
from .deps import client_ip, get_or_404

router = APIRouter(tags=["schedules"])


def _validate_target(db: Session, principal: Principal, target_type: str, target_id: str):
    model = Pipeline if target_type == "pipeline" else Ingestion
    entity = db.get(model, target_id)
    if not entity or entity.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail=f"Scheduled {target_type} not found.")
    return entity


@router.get("/schedules")
def list_schedules(
    principal: Principal = Depends(require("schedules:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(
            select(Schedule)
            .where(Schedule.tenant_id == principal.tenant_id)
            .order_by(Schedule.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [schedule(row) for row in rows]


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
def create_schedule(
    body: ScheduleCreate,
    request: Request,
    principal: Principal = Depends(require("schedules:write")),
    db: Session = Depends(get_session),
) -> dict:
    _validate_target(db, principal, body.target_type, body.target_id)
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(body.timezone)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Invalid timezone.") from exc
    entity = Schedule(
        tenant_id=principal.tenant_id,
        name=body.name,
        target_type=body.target_type,
        target_id=body.target_id,
        cron=body.cron,
        timezone=body.timezone,
        enabled=body.enabled,
        catchup=body.catchup,
        max_concurrent_runs=body.max_concurrent_runs,
        next_run_at=next_run_time(body.cron, body.timezone, datetime.now(UTC)),
    )
    db.add(entity)
    db.flush()
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="schedule.created",
        resource_type="schedule",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"target_type": body.target_type, "target_id": body.target_id, "cron": body.cron},
    )
    db.commit()
    return schedule(entity)


@router.get("/schedules/{schedule_id}")
def get_schedule(
    schedule_id: str,
    principal: Principal = Depends(require("schedules:read")),
    db: Session = Depends(get_session),
) -> dict:
    return schedule(get_or_404(db, Schedule, schedule_id, principal.tenant_id))


@router.patch("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    request: Request,
    principal: Principal = Depends(require("schedules:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Schedule, schedule_id, principal.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(entity, key, value)
    if any(key in changes for key in {"cron", "timezone"}):
        entity.next_run_at = next_run_time(entity.cron, entity.timezone, datetime.now(UTC))
    if changes.get("enabled") is True and not entity.next_run_at:
        entity.next_run_at = next_run_time(entity.cron, entity.timezone, datetime.now(UTC))
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="schedule.updated",
        resource_type="schedule",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"fields": sorted(changes)},
    )
    db.commit()
    return schedule(entity)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str,
    request: Request,
    principal: Principal = Depends(require("schedules:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, Schedule, schedule_id, principal.tenant_id)
    db.delete(entity)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="schedule.deleted",
        resource_type="schedule",
        resource_id=schedule_id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()


@router.post("/schedules/{schedule_id}/run-now", status_code=status.HTTP_202_ACCEPTED)
def run_schedule_now(
    schedule_id: str,
    request: Request,
    principal: Principal = Depends(require("schedules:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Schedule, schedule_id, principal.tenant_id)
    _validate_target(db, principal, entity.target_type, entity.target_id)
    try:
        job = schedule_run(db, entity, trigger="manual-schedule", request_id=request_id_var.get())
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="schedule.run_now",
        resource_type="schedule",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"run_id": job.id, "request_id": job.request_id},
    )
    db.commit()
    return run(job)
