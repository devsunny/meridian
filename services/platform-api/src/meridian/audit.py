from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .context import request_id_var, tenant_id_var, user_id_var
from .logging_setup import get_logger
from .models import AuditEvent, JobRun, RunEvent, Tenant

logger = get_logger("meridian.audit")


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _audit_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode()).hexdigest()


def write_audit(
    session: Session,
    *,
    tenant_id: str,
    action: str,
    resource_type: str,
    resource_id: str = "",
    outcome: str = "success",
    actor_id: str | None = None,
    actor_email: str | None = None,
    data: dict[str, Any] | None = None,
    ip: str = "",
    request_id: str | None = None,
) -> AuditEvent:
    """Append a tamper-evident audit event. The tenant row serialises seq allocation."""
    tenant = session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update()).scalar_one()
    last = session.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()
    seq = (last.seq if last else 0) + 1
    prev_hash = last.hash if last else "GENESIS"
    created_at = datetime.now(UTC)
    event = AuditEvent(
        tenant_id=tenant.id,
        seq=seq,
        actor_id=actor_id or user_id_var.get(),
        actor_email=actor_email or "system",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id or request_id_var.get(),
        ip=ip,
        data=data or {},
        prev_hash=prev_hash,
        created_at=created_at,
    )
    event.hash = _audit_hash(prev_hash, _event_payload(event))
    session.add(event)
    session.flush()
    logger.info(
        "audit_event",
        extra={
            "audit_seq": seq,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome": outcome,
            "tenant_id": tenant_id,
        },
    )
    return event


def _canonical_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event_payload(event: AuditEvent) -> dict[str, Any]:
    return {
        "tenant_id": event.tenant_id,
        "seq": event.seq,
        "actor_id": event.actor_id,
        "actor_email": event.actor_email,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "outcome": event.outcome,
        "request_id": event.request_id,
        "ip": event.ip,
        "data": event.data,
        "created_at": _canonical_timestamp(event.created_at),
    }


def verify_audit_chain(session: Session, tenant_id: str) -> dict[str, Any]:
    events = (
        session.execute(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq.asc())
        )
        .scalars()
        .all()
    )
    prev = "GENESIS"
    for event in events:
        expected = _audit_hash(prev, _event_payload(event))
        if event.prev_hash != prev or event.hash != expected:
            return {
                "valid": False,
                "checked": len(events),
                "broken_at_seq": event.seq,
                "message": "Audit chain integrity check failed.",
            }
        prev = event.hash
    return {
        "valid": True,
        "checked": len(events),
        "head_hash": prev,
        "message": "Audit chain verified.",
    }


def emit_run_event(
    session: Session,
    run: JobRun,
    event_type: str,
    message: str = "",
    data: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> RunEvent:
    seq = (
        session.execute(select(func.max(RunEvent.seq)).where(RunEvent.job_run_id == run.id)).scalar() or 0
    ) + 1
    event = RunEvent(
        tenant_id=run.tenant_id,
        job_run_id=run.id,
        seq=seq,
        type=event_type,
        message=message,
        data=data or {},
        request_id=request_id or run.request_id,
    )
    session.add(event)
    session.flush()
    return event


_ = tenant_id_var
