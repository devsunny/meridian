from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..context import request_id_var
from ..db import SessionLocal, get_session
from ..engine.dag import cancel_run, refresh_run_state, resume_run, retry_run
from ..logging_setup import RunJsonlLogger
from ..models import JobRun, Pipeline, RunEvent, TaskRun
from ..schemas import ApprovalAction, DebugAction
from ..security import Principal, get_principal, require
from ..serializers import dt, run
from .deps import client_ip, run_or_404

router = APIRouter(tags=["runs"])
settings = get_settings()


def _events(db: Session, run_id: str, since: int = 0, limit: int = 500) -> list[dict]:
    rows = (
        db.execute(
            select(RunEvent)
            .where(RunEvent.job_run_id == run_id, RunEvent.seq > since)
            .order_by(RunEvent.seq.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "seq": event.seq,
            "type": event.type,
            "message": event.message,
            "data": event.data or {},
            "request_id": event.request_id,
            "created_at": dt(event.created_at),
        }
        for event in rows
    ]


@router.get("/runs")
def list_runs(
    kind: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    target_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    statement = select(JobRun).where(JobRun.tenant_id == principal.tenant_id)
    if kind:
        statement = statement.where(JobRun.kind == kind)
    if run_status:
        statement = statement.where(JobRun.status == run_status.upper())
    if target_id:
        statement = statement.where(JobRun.target_id == target_id)
    if q:
        like = f"%{q}%"
        statement = statement.where(or_(JobRun.id.ilike(like), JobRun.request_id.ilike(like)))
    rows = (
        db.execute(statement.order_by(JobRun.created_at.desc()).limit(min(limit, 200))).scalars().all()
    )
    return [run(row) for row in rows]


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    tasks = (
        db.execute(select(TaskRun).where(TaskRun.job_run_id == job.id).order_by(TaskRun.created_at)).scalars().all()
    )
    payload = run(job, tasks)
    payload["events"] = _events(db, job.id, 0, 100)
    payload["pipeline"] = None
    if job.kind == "pipeline":
        target = db.get(Pipeline, job.target_id)
        if target:
            payload["pipeline"] = {
                "id": target.id,
                "name": target.name,
                "version": job.pipeline_version,
                "dag": target.dag,
            }
    return payload


@router.get("/runs/{run_id}/tasks")
def get_run_tasks(
    run_id: str,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    job = run_or_404(db, principal.tenant_id, run_id)
    from ..serializers import task as serialize_task

    tasks = (
        db.execute(select(TaskRun).where(TaskRun.job_run_id == job.id).order_by(TaskRun.created_at)).scalars().all()
    )
    return [serialize_task(item) for item in tasks]


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: str,
    since: int = 0,
    limit: int = 500,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    events = _events(db, job.id, since, limit)
    return {"events": events, "run_status": job.status, "request_id": request_id_var.get()}


@router.get("/runs/{run_id}/events/stream")
def stream_run_events(
    run_id: str,
    since: int = 0,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_session),
):
    job = run_or_404(db, principal.tenant_id, run_id)
    tenant_id = job.tenant_id

    async def generator():
        last = since
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                events = (
                    session.execute(
                        select(RunEvent)
                        .where(RunEvent.job_run_id == run_id, RunEvent.seq > last)
                        .order_by(RunEvent.seq.asc())
                        .limit(200)
                    )
                    .scalars()
                    .all()
                )
                current = session.get(JobRun, run_id)
                if current is None or current.tenant_id != tenant_id:
                    break
                for event in events:
                    last = event.seq
                    payload = {
                        "seq": event.seq,
                        "type": event.type,
                        "message": event.message,
                        "data": event.data or {},
                        "request_id": event.request_id,
                        "created_at": dt(event.created_at),
                    }
                    yield f"id: {event.seq}\ndata: {json.dumps(payload, default=str)}\n\n"
                if current.status in {"SUCCEEDED", "FAILED", "CANCELLED"} and not events:
                    break
            await asyncio.sleep(1.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/logs")
def get_run_logs(
    run_id: str,
    limit: int = 2000,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    logger = RunJsonlLogger(settings.log_dir, job.tenant_id, job.id)
    entries = logger.read(limit=min(limit, 5000))
    if not entries:
        entries = [
            {
                "timestamp": dt(event.created_at),
                "level": "INFO" if event.type != "task.failed" else "ERROR",
                "message": event.message,
                "request_id": event.request_id,
                "run_id": job.id,
                "event_type": event.type,
                "data": event.data,
            }
            for event in db.execute(
                select(RunEvent).where(RunEvent.job_run_id == job.id).order_by(RunEvent.seq.asc())
            )
            .scalars()
            .all()
        ]
    return {
        "run_id": job.id,
        "entries": entries,
        "format": "jsonl",
        "request_id": request_id_var.get(),
    }


@router.post("/runs/{run_id}/cancel")
def cancel(
    run_id: str,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    if job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"Run is already {job.status}.")
    cancel_run(db, job, reason=f"Cancelled by {principal.email}")
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.cancelled",
        resource_type="pipeline_run" if job.kind == "pipeline" else "ingestion_run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()
    return run(job)


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(
    run_id: str,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    new_run = retry_run(db, job, request_id=request_id_var.get(), created_by=principal.email)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.retried",
        resource_type="pipeline_run" if job.kind == "pipeline" else "ingestion_run",
        resource_id=new_run.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"previous_run_id": job.id},
    )
    db.commit()
    return run(new_run)


@router.post("/runs/{run_id}/pause")
def pause(
    run_id: str,
    body: DebugAction,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    if job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"Run is already {job.status}.")
    job.pause_requested = True
    job.status = "PAUSED"
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.paused",
        resource_type="run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"note": body.note},
    )
    db.commit()
    return run(job)


@router.post("/runs/{run_id}/resume")
def resume(
    run_id: str,
    body: DebugAction,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    try:
        task = resume_run(db, job, body.task_id, approve=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.resumed",
        resource_type="run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"task_id": task.task_id, "note": body.note},
    )
    db.commit()
    return run(job)


@router.post("/runs/{run_id}/step")
def step(
    run_id: str,
    body: DebugAction,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    try:
        task = resume_run(db, job, body.task_id, approve=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="debug.step",
        resource_type="run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"task_id": task.task_id},
    )
    db.commit()
    return {"run": run(job), "resumed_task": task.task_id, "request_id": request_id_var.get()}


@router.post("/runs/{run_id}/approve")
def approve(
    run_id: str,
    body: ApprovalAction,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    try:
        task = resume_run(db, job, body.task_id, approve=body.approve)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    refresh_run_state(db, job)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.approved" if body.approve else "run.rejected",
        resource_type="run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"task_id": task.task_id, "note": body.note},
    )
    db.commit()
    return run(job)


@router.get("/runs/{run_id}/debug")
def debug_state(
    run_id: str,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> dict:
    job = run_or_404(db, principal.tenant_id, run_id)
    tasks = (
        db.execute(select(TaskRun).where(TaskRun.job_run_id == job.id).order_by(TaskRun.created_at)).scalars().all()
    )
    paused = [task for task in tasks if task.status == "PAUSED"]
    return {
        "run_id": job.id,
        "debug": job.debug,
        "status": job.status,
        "pause_requested": job.pause_requested,
        "paused_tasks": [
            {
                "task_id": task.task_id,
                "name": task.name,
                "type": task.type,
                "breakpoint": bool(task.spec.get("_breakpoint")),
                "reason": task.error,
            }
            for task in paused
        ],
        "breakpoint_tasks": [task.task_id for task in tasks if task.spec.get("_breakpoint")],
        "request_id": request_id_var.get(),
    }
