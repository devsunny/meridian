from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from ..config import get_settings
from ..context import bind_run, unbind
from ..db import init_db, metrics, session_scope
from ..logging_setup import RunJsonlLogger, configure_logging, get_logger
from ..models import JobRun, TaskRun
from ..telemetry import configure_telemetry, span
from .dag import (
    claim_task,
    complete_task,
    fail_task,
    pause_for_approval,
    pause_for_debug,
    should_debug_pause,
)
from .tasks import TaskFailure, TaskPaused, execute_task

settings = get_settings()
logger = get_logger("meridian.worker")
_stop = threading.Event()


def _worker_id() -> str:
    configured = settings.worker_id
    suffix = uuid.uuid4().hex[:6]
    host = socket.gethostname()
    return f"{configured or host}-{os.getpid()}-{suffix}"


def process_one(worker_id: str) -> bool:
    with session_scope() as session:
        claimed = claim_task(session, worker_id)
        if not claimed:
            return False
        task_id = claimed.id
        run_id = claimed.job_run_id
        request_id = claimed.request_id
        tenant_id = claimed.tenant_id
    tokens = bind_run(run_id, request_id, tenant_id, task_id)
    try:
        _execute_claimed(task_id)
        return True
    finally:
        unbind(tokens)


def _execute_claimed(task_id: str) -> None:
    with session_scope() as session:
        task = session.get(TaskRun, task_id)
        run = session.get(JobRun, task.job_run_id) if task else None
        if not task or not run:
            return
        run_log = RunJsonlLogger(settings.log_dir, task.tenant_id, run.id)
        if run.pause_requested:
            task.status = "QUEUED"
            task.worker_id = None
            task.attempt = max(0, task.attempt - 1)
            run.status = "PAUSED"
            session.add_all([task, run])
            return
        if should_debug_pause(run, task):
            pause_for_debug(session, task, run)
            run_log.write("INFO", "Debug breakpoint hit", task_id=task.task_id, breakpoint=True)
            return
        logger.info(
            "task_started",
            extra={
                "task_type": task.type,
                "task_name": task.name,
                "attempt": task.attempt,
                "run_id": run.id,
                "task_id": task.task_id,
            },
        )
        run_log.write(
            "INFO",
            f"Task {task.name} started (attempt {task.attempt}/{task.max_attempts})",
            task_id=task.task_id,
            task_type=task.type,
        )
        metrics.inc("meridian_task_runs", status="started", type=task.type)
        started = time.perf_counter()
        try:
            with span("task.execute", {"run_id": run.id, "task_id": task.task_id, "task_type": task.type}):
                result = execute_task(session, run, task)
            duration = time.perf_counter() - started
            complete_task(session, task, run, output=result.output, duration_seconds=duration)
            metrics.inc("meridian_task_runs", status="succeeded", type=task.type)
            metrics.observe("meridian_task_duration_seconds", duration, type=task.type)
            run_log.write(
                "INFO",
                f"Task {task.name} succeeded in {duration:.2f}s",
                task_id=task.task_id,
                output=result.output,
            )
            if run.status in {"SUCCEEDED", "FAILED"}:
                run_log.write("INFO", f"Run finished with status {run.status}", status=run.status)
            logger.info(
                "task_succeeded",
                extra={"run_id": run.id, "task_id": task.task_id, "duration_seconds": round(duration, 3)},
            )
            session.commit()
        except TaskPaused as exc:
            session.rollback()
            task = session.get(TaskRun, task_id)
            run = session.get(JobRun, task.job_run_id) if task else None
            if task and run:
                pause_for_approval(session, task, run, str(exc))
                run_log.write("WARN", str(exc), task_id=task.task_id)
                metrics.inc("meridian_task_runs", status="paused", type=task.type)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            task = session.get(TaskRun, task_id)
            run = session.get(JobRun, task.job_run_id) if task else None
            if not task or not run:
                return
            if isinstance(exc, TaskFailure):
                retryable = exc.retryable
                message = str(exc)
            else:
                from edp_connector_sdk import ConnectorError

                retryable = not isinstance(exc, ConnectorError) or exc.retryable
                message = str(exc) if isinstance(exc, ConnectorError) else f"{exc.__class__.__name__}: {exc}"
            message = message[:4000]
            fail_task(session, task, run, message, retryable=retryable)
            metrics.inc("meridian_task_runs", status="failed", type=task.type)
            run_log.write("ERROR", f"Task {task.name} failed: {message}", task_id=task.task_id)
            logger.exception(
                "task_failed",
                extra={"run_id": run.id, "task_id": task.task_id, "retryable": retryable},
            )
            session.commit()
    _ = datetime


def recover_orphaned_tasks() -> None:
    """Best-effort recovery for workers that died with RUNNING tasks."""
    cutoff = datetime.now(UTC).timestamp() - settings.task_default_timeout_seconds
    with session_scope() as session:
        tasks = (
            session.execute(select(TaskRun).where(TaskRun.status == "RUNNING").limit(100)).scalars().all()
        )
        for task in tasks:
            if task.started_at and task.started_at.timestamp() < cutoff:
                run = session.get(JobRun, task.job_run_id)
                if run:
                    logger.warning("task_orphaned", extra={"task_id": task.id, "run_id": run.id})
                    fail_task(session, task, run, "Worker lease expired; task requeued.", retryable=True)


def run_loop(worker_id: str, concurrency: int) -> None:
    if concurrency <= 1:
        while not _stop.is_set():
            try:
                if not process_one(worker_id):
                    _stop.wait(settings.worker_poll_seconds)
            except Exception:  # noqa: BLE001
                logger.exception("worker_loop_error")
                _stop.wait(2)
        return

    threads: list[threading.Thread] = []

    def loop(index: int) -> None:
        child_id = f"{worker_id}-{index}"
        while not _stop.is_set():
            try:
                if not process_one(child_id):
                    _stop.wait(settings.worker_poll_seconds)
            except Exception:  # noqa: BLE001
                logger.exception("worker_loop_error", extra={"worker_index": index})
                _stop.wait(2)

    for index in range(concurrency):
        thread = threading.Thread(target=loop, args=(index,), name=f"meridian-worker-{index}", daemon=True)
        thread.start()
        threads.append(thread)
    while not _stop.is_set():
        _stop.wait(1)
    for thread in threads:
        thread.join(timeout=10)


def main() -> None:
    configure_logging("meridian-worker")
    configure_telemetry("meridian-worker")
    init_db(seed=True)
    worker_id = _worker_id()
    logger.info(
        "worker_started",
        extra={"worker_id": worker_id, "concurrency": settings.worker_concurrency, "db": settings.database_url.split("@")[-1]},
    )
    recover_orphaned_tasks()

    def handle_signal(signum, frame):  # type: ignore[no-untyped-def]
        logger.info("worker_stopping", extra={"signal": signum})
        _stop.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), handle_signal)
    try:
        run_loop(worker_id, max(1, settings.worker_concurrency))
    finally:
        logger.info("worker_stopped", extra={"worker_id": worker_id})


def cli() -> None:
    parser = argparse.ArgumentParser(description="Meridian task worker")
    parser.add_argument("--once", action="store_true", help="Process at most one task and exit")
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()
    if args.once:
        configure_logging("meridian-worker")
        init_db(seed=True)
        worker_id = _worker_id()
        processed = process_one(worker_id)
        logging.getLogger("meridian.worker").info("worker_once", extra={"processed": processed})
        return
    if args.concurrency:
        settings.worker_concurrency = args.concurrency
    main()


if __name__ == "__main__":
    cli()
