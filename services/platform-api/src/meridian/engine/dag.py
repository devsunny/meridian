from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..audit import emit_run_event
from ..config import get_settings
from ..context import new_id
from ..logging_setup import get_logger
from ..models import Ingestion, JobRun, Pipeline, PipelineVersion, Schedule, TaskRun
from ..schemas import DagSpec

logger = get_logger("meridian.dag")
settings = get_settings()

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED"}


def normalize_dag(raw: dict[str, Any] | DagSpec) -> dict[str, Any]:
    spec = raw if isinstance(raw, DagSpec) else DagSpec.model_validate(raw)
    # Persist positions/naming while ensuring dependencies are derived.
    return spec.to_dict()


def create_pipeline_run(
    session: Session,
    pipeline: Pipeline,
    *,
    request_id: str,
    created_by: str,
    trigger: str = "manual",
    debug: bool = False,
    schedule_id: str | None = None,
    logical_date: datetime | None = None,
    idempotency_key: str | None = None,
) -> JobRun:
    if not pipeline.dag or not pipeline.dag.get("nodes"):
        raise ValueError("Pipeline has no DAG. Save a workflow before running it.")
    key = idempotency_key or f"manual:{pipeline.id}:{new_id()}"
    existing = session.execute(select(JobRun).where(JobRun.idempotency_key == key)).scalar_one_or_none()
    if existing:
        return existing
    run = JobRun(
        tenant_id=pipeline.tenant_id,
        kind="pipeline",
        target_id=pipeline.id,
        pipeline_version=pipeline.current_version,
        status="QUEUED",
        trigger=trigger,
        request_id=request_id,
        idempotency_key=key,
        logical_date=logical_date or datetime.now(UTC),
        debug=debug,
        created_by=created_by,
        schedule_id=schedule_id,
    )
    session.add(run)
    session.flush()
    version = session.execute(
        select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id,
            PipelineVersion.version == pipeline.current_version,
        )
    ).scalar_one_or_none()
    dag = version.dag if version else pipeline.dag
    _materialize_tasks(session, run, dag)
    emit_run_event(
        session,
        run,
        "run.created",
        f"Run created from {trigger} trigger.",
        {"pipeline_id": pipeline.id, "version": pipeline.current_version, "debug": debug},
        request_id,
    )
    session.flush()
    refresh_run_state(session, run)
    return run


def create_ingestion_run(
    session: Session,
    ingestion: Ingestion,
    *,
    request_id: str,
    created_by: str,
    trigger: str = "manual",
    schedule_id: str | None = None,
    logical_date: datetime | None = None,
    idempotency_key: str | None = None,
) -> JobRun:
    key = idempotency_key or f"manual-ingest:{ingestion.id}:{new_id()}"
    existing = session.execute(select(JobRun).where(JobRun.idempotency_key == key)).scalar_one_or_none()
    if existing:
        return existing
    run = JobRun(
        tenant_id=ingestion.tenant_id,
        kind="ingestion",
        target_id=ingestion.id,
        status="QUEUED",
        trigger=trigger,
        request_id=request_id,
        idempotency_key=key,
        logical_date=logical_date or datetime.now(UTC),
        created_by=created_by,
        schedule_id=schedule_id,
    )
    session.add(run)
    session.flush()
    session.add(
        TaskRun(
            tenant_id=ingestion.tenant_id,
            job_run_id=run.id,
            task_id="ingest",
            name=f"Ingest {ingestion.name}",
            type="ingestion.run",
            spec={"ingestion_id": ingestion.id, "_max_records": ingestion.spec.get("max_records")},
            depends_on=[],
            status="QUEUED",
            attempt=0,
            max_attempts=settings.task_max_attempts,
            timeout_seconds=settings.task_default_timeout_seconds,
            request_id=request_id,
        )
    )
    emit_run_event(
        session,
        run,
        "run.created",
        f"Ingestion run created from {trigger} trigger.",
        {"ingestion_id": ingestion.id},
        request_id,
    )
    session.flush()
    return run


def _materialize_tasks(session: Session, run: JobRun, dag: dict[str, Any]) -> None:
    nodes = dag.get("nodes", [])
    ready_ids = {node["id"] for node in nodes if not node.get("depends_on")}
    for node in nodes:
        spec = dict(node.get("config") or {})
        spec["_breakpoint"] = bool(node.get("breakpoint", False))
        spec["_node_name"] = node.get("name") or node["id"]
        session.add(
            TaskRun(
                tenant_id=run.tenant_id,
                job_run_id=run.id,
                task_id=node["id"],
                name=node.get("name") or node["id"],
                type=node["type"],
                spec=spec,
                depends_on=list(node.get("depends_on") or []),
                status="QUEUED" if node["id"] in ready_ids else "PENDING",
                attempt=0,
                max_attempts=int(node.get("max_attempts") or settings.task_max_attempts),
                timeout_seconds=int(node.get("timeout_seconds") or settings.task_default_timeout_seconds),
                request_id=run.request_id,
                debug_hit=False,
            )
        )
    session.flush()


def refresh_run_state(session: Session, run: JobRun) -> JobRun:
    tasks = (
        session.execute(select(TaskRun).where(TaskRun.job_run_id == run.id).order_by(TaskRun.created_at)).scalars().all()
    )
    if not tasks:
        return run
    statuses = [task.status for task in tasks]
    if run.status == "CANCELLED":
        return run
    if "FAILED" in statuses:
        if all(status in TERMINAL for status in statuses):
            run.status = "FAILED"
            run.ended_at = run.ended_at or datetime.now(UTC)
    elif all(status in {"SUCCEEDED", "SKIPPED"} for status in statuses):
        run.status = "SUCCEEDED"
        run.ended_at = run.ended_at or datetime.now(UTC)
    elif any(status == "RUNNING" for status in statuses):
        run.status = "RUNNING"
        run.started_at = run.started_at or datetime.now(UTC)
    elif any(status == "PAUSED" for status in statuses):
        run.status = "PAUSED"
    elif any(status in {"QUEUED", "PENDING"} for status in statuses):
        run.status = "QUEUED"
    session.add(run)
    session.flush()
    return run


def enqueue_ready_tasks(session: Session, run: JobRun) -> None:
    tasks = (
        session.execute(select(TaskRun).where(TaskRun.job_run_id == run.id).order_by(TaskRun.created_at)).scalars().all()
    )
    by_id = {task.task_id: task for task in tasks}
    changed = False
    for task in tasks:
        if task.status not in {"PENDING", "QUEUED"}:
            continue
        dependencies = [by_id.get(dependency) for dependency in (task.depends_on or [])]
        if any(dependency is None for dependency in dependencies):
            task.status = "SKIPPED"
            task.error = "A dependency was not materialized."
            changed = True
            continue
        if any(dependency.status in {"FAILED", "SKIPPED", "CANCELLED"} for dependency in dependencies):
            if task.status != "SKIPPED":
                task.status = "SKIPPED"
                task.error = "Skipped because an upstream task did not succeed."
                changed = True
                emit_run_event(
                    session,
                    run,
                    "task.skipped",
                    f"Task {task.name} skipped: upstream failure.",
                    {"task_id": task.task_id},
                    run.request_id,
                )
            continue
        if task.status == "PENDING" and dependencies and all(
            dependency.status == "SUCCEEDED" for dependency in dependencies
        ):
            task.status = "QUEUED"
            changed = True
            emit_run_event(
                session,
                run,
                "task.queued",
                f"Task {task.name} queued.",
                {"task_id": task.task_id},
                run.request_id,
            )
        elif task.status == "PENDING" and not dependencies:
            task.status = "QUEUED"
            changed = True
    if changed:
        session.flush()


def claim_task(session: Session, worker_id: str) -> TaskRun | None:
    now = datetime.now(UTC)
    statement = (
        select(TaskRun)
        .where(TaskRun.status == "QUEUED", TaskRun.available_at <= now)
        .order_by(TaskRun.available_at.asc(), TaskRun.created_at.asc())
        .limit(1)
    )
    with contextlib.suppress(Exception):
        statement = statement.with_for_update(skip_locked=True)
    task = session.execute(statement).scalar_one_or_none()
    if not task:
        return None
    run = session.get(JobRun, task.job_run_id)
    if not run or run.status == "CANCELLED":
        session.execute(
            update(TaskRun)
            .where(TaskRun.id == task.id, TaskRun.status == "QUEUED")
            .values(status="CANCELLED", ended_at=now)
        )
        session.commit()
        return None
    if run.pause_requested:
        # Do not consume the task; the run will be resumed by the operator.
        session.rollback()
        return None
    # This conditional UPDATE is the cross-process lease. On PostgreSQL the row is
    # already locked; on SQLite it closes the gap where several readers can select
    # the same QUEUED row before either writer commits.
    claimed = session.execute(
        update(TaskRun)
        .where(TaskRun.id == task.id, TaskRun.status == "QUEUED")
        .values(
            status="RUNNING",
            worker_id=worker_id,
            attempt=TaskRun.attempt + 1,
            started_at=now,
        )
    )
    if claimed.rowcount != 1:
        session.rollback()
        return None
    run.status = "RUNNING"
    run.started_at = run.started_at or now
    session.add(run)
    session.commit()
    session.refresh(task)
    return task


def should_debug_pause(run: JobRun, task: TaskRun) -> bool:
    return bool(run.debug and task.spec.get("_breakpoint") and not task.debug_hit)


def complete_task(
    session: Session,
    task: TaskRun,
    run: JobRun,
    *,
    output: dict[str, Any],
    duration_seconds: float,
) -> None:
    task.status = "SUCCEEDED"
    task.output = output
    task.error = None
    task.ended_at = datetime.now(UTC)
    run.output = {**(run.output or {}), task.task_id: output}
    session.add_all([task, run])
    emit_run_event(
        session,
        run,
        "task.succeeded",
        f"Task {task.name} succeeded.",
        {"task_id": task.task_id, "duration_seconds": round(duration_seconds, 3), "output": output},
        run.request_id,
    )
    session.flush()
    enqueue_ready_tasks(session, run)
    refresh_run_state(session, run)


def fail_task(session: Session, task: TaskRun, run: JobRun, error: str, *, retryable: bool = True) -> None:
    now = datetime.now(UTC)
    if retryable and task.attempt < task.max_attempts:
        backoff = min(300, 2 ** max(task.attempt - 1, 0) * 5)
        task.status = "QUEUED"
        task.error = error
        task.available_at = now + timedelta(seconds=backoff)
        task.ended_at = None
        task.worker_id = None
        emit_run_event(
            session,
            run,
            "task.retry",
            f"Task {task.name} failed; retry {task.attempt}/{task.max_attempts} in {backoff}s.",
            {"task_id": task.task_id, "error": error, "backoff_seconds": backoff},
            run.request_id,
        )
    else:
        task.status = "FAILED"
        task.error = error
        task.ended_at = now
        run.error = error[:2000]
        emit_run_event(
            session,
            run,
            "task.failed",
            f"Task {task.name} failed.",
            {"task_id": task.task_id, "error": error},
            run.request_id,
        )
        enqueue_ready_tasks(session, run)
        refresh_run_state(session, run)
    session.add_all([task, run])
    session.flush()


def pause_for_debug(session: Session, task: TaskRun, run: JobRun) -> None:
    task.status = "PAUSED"
    task.debug_hit = True
    task.worker_id = None
    run.status = "PAUSED"
    session.add_all([task, run])
    emit_run_event(
        session,
        run,
        "debug.paused",
        f"Breakpoint hit at {task.name}.",
        {"task_id": task.task_id, "breakpoint": True},
        run.request_id,
    )
    session.flush()


def pause_for_approval(session: Session, task: TaskRun, run: JobRun, reason: str) -> None:
    task.status = "PAUSED"
    task.error = reason
    task.worker_id = None
    run.status = "PAUSED"
    session.add_all([task, run])
    emit_run_event(
        session,
        run,
        "approval.required",
        reason,
        {"task_id": task.task_id, "type": "approval"},
        run.request_id,
    )
    session.flush()


def resume_run(session: Session, run: JobRun, task_id: str | None = None, *, approve: bool = True) -> TaskRun:
    query = select(TaskRun).where(TaskRun.job_run_id == run.id, TaskRun.status == "PAUSED")
    if task_id:
        query = query.where(TaskRun.task_id == task_id)
    task = session.execute(query.order_by(TaskRun.created_at)).scalars().first()
    if not task:
        raise ValueError("No paused task is available to resume.")
    if task.type == "approval":
        if not approve:
            task.status = "FAILED"
            task.error = "Approval rejected."
            run.error = "Approval rejected."
        else:
            task.status = "SUCCEEDED"
            task.output = {"approved": True, "request_id": run.request_id}
    else:
        task.status = "QUEUED"
        task.available_at = datetime.now(UTC)
        task.debug_hit = True
    task.worker_id = None
    run.pause_requested = False
    run.status = "RUNNING"
    run.error = None
    session.add_all([task, run])
    emit_run_event(
        session,
        run,
        "run.resumed",
        f"Resumed task {task.name}.",
        {"task_id": task.task_id},
        run.request_id,
    )
    session.flush()
    enqueue_ready_tasks(session, run)
    refresh_run_state(session, run)
    return task


def cancel_run(session: Session, run: JobRun, reason: str = "Cancelled by operator") -> None:
    tasks = session.execute(select(TaskRun).where(TaskRun.job_run_id == run.id)).scalars().all()
    for task in tasks:
        if task.status in {"QUEUED", "PENDING", "PAUSED"}:
            task.status = "CANCELLED"
            task.ended_at = datetime.now(UTC)
    run.status = "CANCELLED"
    run.error = reason
    run.ended_at = datetime.now(UTC)
    session.add(run)
    emit_run_event(session, run, "run.cancelled", reason, {}, run.request_id)
    session.flush()


def retry_run(session: Session, run: JobRun, *, request_id: str, created_by: str) -> JobRun:
    if run.kind == "pipeline":
        pipeline = session.get(Pipeline, run.target_id)
        if not pipeline:
            raise ValueError("Pipeline no longer exists.")
        return create_pipeline_run(
            session,
            pipeline,
            request_id=request_id,
            created_by=created_by,
            trigger=f"retry:{run.id}",
            debug=run.debug,
            idempotency_key=f"retry:{run.id}:{new_id()}",
        )
    ingestion = session.get(Ingestion, run.target_id)
    if not ingestion:
        raise ValueError("Ingestion no longer exists.")
    return create_ingestion_run(
        session,
        ingestion,
        request_id=request_id,
        created_by=created_by,
        trigger=f"retry:{run.id}",
        idempotency_key=f"retry:{run.id}:{new_id()}",
    )


def next_run_time(cron: str, timezone: str, base: datetime | None = None) -> datetime:
    from zoneinfo import ZoneInfo

    from croniter import croniter

    zone = ZoneInfo(timezone)
    base_local = (base or datetime.now(UTC)).astimezone(zone)
    next_local = croniter(cron, base_local).get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=zone)
    return next_local.astimezone(UTC)


def schedule_run(
    session: Session,
    schedule: Schedule,
    *,
    trigger: str = "schedule",
    logical_date: datetime | None = None,
    request_id: str | None = None,
) -> JobRun:
    from ..context import new_request_id

    rid = request_id or new_request_id()
    logical = logical_date or schedule.next_run_at or datetime.now(UTC)
    if schedule.target_type == "pipeline":
        pipeline = session.get(Pipeline, schedule.target_id)
        if not pipeline:
            raise ValueError("Scheduled pipeline no longer exists.")
        active = session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(
                JobRun.tenant_id == schedule.tenant_id,
                JobRun.target_id == pipeline.id,
                JobRun.status.in_(["QUEUED", "RUNNING", "PAUSED"]),
            )
        ).scalar() or 0
        if active >= schedule.max_concurrent_runs:
            raise RuntimeError("Concurrency limit reached; schedule run skipped.")
        run = create_pipeline_run(
            session,
            pipeline,
            request_id=rid,
            created_by=f"scheduler:{schedule.id}",
            trigger=trigger,
            schedule_id=schedule.id,
            logical_date=logical,
            idempotency_key=f"schedule:{schedule.id}:{logical.isoformat()}",
        )
    elif schedule.target_type == "ingestion":
        ingestion = session.get(Ingestion, schedule.target_id)
        if not ingestion:
            raise ValueError("Scheduled ingestion no longer exists.")
        active = session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(
                JobRun.tenant_id == schedule.tenant_id,
                JobRun.target_id == ingestion.id,
                JobRun.status.in_(["QUEUED", "RUNNING", "PAUSED"]),
            )
        ).scalar() or 0
        if active >= schedule.max_concurrent_runs:
            raise RuntimeError("Concurrency limit reached; schedule run skipped.")
        run = create_ingestion_run(
            session,
            ingestion,
            request_id=rid,
            created_by=f"scheduler:{schedule.id}",
            trigger=trigger,
            schedule_id=schedule.id,
            logical_date=logical,
            idempotency_key=f"schedule:{schedule.id}:{logical.isoformat()}",
        )
    else:
        raise ValueError(f"Unknown schedule target type: {schedule.target_type}")
    schedule.last_run_at = datetime.now(UTC)
    schedule.next_run_at = next_run_time(schedule.cron, schedule.timezone, datetime.now(UTC))
    session.add(schedule)
    session.flush()
    return run


def task_graph(run: JobRun, tasks: list[TaskRun]) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "nodes": [
            {
                "id": task.task_id,
                "name": task.name,
                "type": task.type,
                "status": task.status,
                "attempt": task.attempt,
                "max_attempts": task.max_attempts,
                "depends_on": task.depends_on,
                "error": task.error,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "ended_at": task.ended_at.isoformat() if task.ended_at else None,
                "output": task.output,
            }
            for task in tasks
        ],
    }
