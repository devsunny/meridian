from __future__ import annotations

import contextlib
import signal
import threading
from datetime import UTC, datetime

from sqlalchemy import select

from ..config import get_settings
from ..context import new_request_id, request_context
from ..db import init_db, metrics, session_scope
from ..logging_setup import configure_logging, get_logger
from ..models import Schedule
from ..telemetry import configure_telemetry
from .dag import next_run_time, schedule_run

settings = get_settings()
logger = get_logger("meridian.scheduler")
_stop = threading.Event()


def materialize_due_schedules(limit: int = 20) -> int:
    created = 0
    now = datetime.now(UTC)
    with session_scope() as session:
        statement = (
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at.is_not(None), Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at.asc())
            .limit(limit)
        )
        with contextlib.suppress(Exception):
            statement = statement.with_for_update(skip_locked=True)
        schedules = session.execute(statement).scalars().all()
        for schedule in schedules:
            with request_context(request_id=new_request_id(), tenant_id=schedule.tenant_id):
                try:
                    run = schedule_run(session, schedule, trigger="schedule")
                    created += 1
                    logger.info(
                        "schedule_materialized",
                        extra={
                            "schedule_id": schedule.id,
                            "run_id": run.id,
                            "target_type": schedule.target_type,
                            "target_id": schedule.target_id,
                        },
                    )
                except RuntimeError as exc:
                    logger.warning(
                        "schedule_skipped",
                        extra={"schedule_id": schedule.id, "reason": str(exc)},
                    )
                    schedule.next_run_at = next_run_time(schedule.cron, schedule.timezone, now)
                    session.add(schedule)
                except Exception:  # noqa: BLE001
                    logger.exception("schedule_failed", extra={"schedule_id": schedule.id})
                    schedule.next_run_at = next_run_time(schedule.cron, schedule.timezone, now)
                    session.add(schedule)
                session.commit()
    return created


def main() -> None:
    configure_logging("meridian-scheduler")
    configure_telemetry("meridian-scheduler")
    init_db(seed=True)
    logger.info("scheduler_started", extra={"poll_seconds": settings.scheduler_poll_seconds})

    def handle_signal(signum, frame):  # type: ignore[no-untyped-def]
        logger.info("scheduler_stopping", extra={"signal": signum})
        _stop.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), handle_signal)
    while not _stop.is_set():
        try:
            created = materialize_due_schedules()
            metrics.gauge("meridian_scheduler_due_runs_created", created)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler_tick_failed")
        _stop.wait(settings.scheduler_poll_seconds)
    logger.info("scheduler_stopped")


if __name__ == "__main__":
    main()
