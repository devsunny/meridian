from __future__ import annotations

from datetime import UTC
from typing import Any

from .models import (
    AccessGrant,
    AccessRequest,
    AuditEvent,
    Connection,
    Dataset,
    ExternalSystem,
    Ingestion,
    JobRun,
    Pipeline,
    Schedule,
    TaskRun,
)
from .secrets import redact_config


def dt(value) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def connection(c: Connection) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "type": c.type,
        "description": c.description,
        "config": redact_config(c.config or {}),
        "secret_ref": c.secret_ref,
        "has_secret": bool(c.secret_ref),
        "status": c.status,
        "owner": c.owner,
        "last_tested_at": dt(c.last_tested_at),
        "last_test_ok": c.last_test_ok,
        "created_at": dt(c.created_at),
        "updated_at": dt(c.updated_at),
    }


def ingestion(i: Ingestion) -> dict[str, Any]:
    return {
        "id": i.id,
        "name": i.name,
        "description": i.description,
        "connection_id": i.connection_id,
        "target_dataset": i.target_dataset,
        "spec": i.spec or {},
        "schedule_cron": i.schedule_cron,
        "schedule_timezone": i.schedule_timezone,
        "status": i.status,
        "owner": i.owner,
        "last_run_id": i.last_run_id,
        "last_run_at": dt(i.last_run_at),
        "created_at": dt(i.created_at),
        "updated_at": dt(i.updated_at),
    }


def pipeline(p: Pipeline) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "owner": p.owner,
        "status": p.status,
        "current_version": p.current_version,
        "dag": p.dag or {"nodes": [], "edges": []},
        "created_at": dt(p.created_at),
        "updated_at": dt(p.updated_at),
    }


def schedule(s: Schedule) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "target_type": s.target_type,
        "target_id": s.target_id,
        "cron": s.cron,
        "timezone": s.timezone,
        "enabled": s.enabled,
        "catchup": s.catchup,
        "max_concurrent_runs": s.max_concurrent_runs,
        "next_run_at": dt(s.next_run_at),
        "last_run_at": dt(s.last_run_at),
        "created_at": dt(s.created_at),
    }


def task(t: TaskRun) -> dict[str, Any]:
    return {
        "id": t.id,
        "task_id": t.task_id,
        "name": t.name,
        "type": t.type,
        "status": t.status,
        "attempt": t.attempt,
        "max_attempts": t.max_attempts,
        "depends_on": t.depends_on or [],
        "breakpoint": bool((t.spec or {}).get("_breakpoint")),
        "output": t.output or {},
        "error": t.error,
        "worker_id": t.worker_id,
        "request_id": t.request_id,
        "started_at": dt(t.started_at),
        "ended_at": dt(t.ended_at),
        "spec": {k: v for k, v in (t.spec or {}).items() if not k.startswith("_")},
    }


def run(r: JobRun, tasks: list[TaskRun] | None = None) -> dict[str, Any]:
    payload = {
        "id": r.id,
        "kind": r.kind,
        "target_id": r.target_id,
        "pipeline_version": r.pipeline_version,
        "status": r.status,
        "trigger": r.trigger,
        "request_id": r.request_id,
        "logical_date": dt(r.logical_date),
        "debug": r.debug,
        "pause_requested": r.pause_requested,
        "created_by": r.created_by,
        "schedule_id": r.schedule_id,
        "error": r.error,
        "output": r.output or {},
        "started_at": dt(r.started_at),
        "ended_at": dt(r.ended_at),
        "created_at": dt(r.created_at),
    }
    if tasks is not None:
        payload["tasks"] = [task(t) for t in tasks]
        payload["task_graph"] = {
            "nodes": [
                {
                    "id": t.task_id,
                    "name": t.name,
                    "type": t.type,
                    "status": t.status,
                    "depends_on": t.depends_on or [],
                }
                for t in tasks
            ]
        }
    return payload


def dataset(d: Dataset) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "layer": d.layer,
        "format": d.format,
        "classification": d.classification,
        "owner": d.owner,
        "location": d.location,
        "row_count": d.row_count,
        "size_bytes": d.size_bytes,
        "version": d.version,
        "schema": d.schema_json or [],
        "profile": d.profile or {},
        "source_connection_id": d.source_connection_id,
        "source_uri": d.source_uri,
        "created_at": dt(d.created_at),
        "updated_at": dt(d.updated_at),
    }


def access_request(r: AccessRequest) -> dict[str, Any]:
    return {
        "id": r.id,
        "requester_email": r.requester_email,
        "dataset_id": r.dataset_id,
        "action": r.action,
        "purpose": r.purpose,
        "duration_days": r.duration_days,
        "status": r.status,
        "decision_reason": r.decision_reason,
        "expires_at": dt(r.expires_at),
        "created_at": dt(r.created_at),
        "decided_at": dt(r.decided_at),
    }


def grant(g: AccessGrant) -> dict[str, Any]:
    return {
        "id": g.id,
        "principal_email": g.principal_email,
        "dataset_id": g.dataset_id,
        "action": g.action,
        "granted_by": g.granted_by,
        "expires_at": dt(g.expires_at),
        "revoked_at": dt(g.revoked_at),
        "created_at": dt(g.created_at),
    }


def audit(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "seq": e.seq,
        "actor_id": e.actor_id,
        "actor_email": e.actor_email,
        "action": e.action,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "outcome": e.outcome,
        "request_id": e.request_id,
        "ip": e.ip,
        "data": e.data or {},
        "hash": e.hash,
        "prev_hash": e.prev_hash,
        "created_at": dt(e.created_at),
    }


def external_system(e: ExternalSystem) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "type": e.type,
        "base_url": e.base_url,
        "secret_ref": e.secret_ref,
        "has_secret": bool(e.secret_ref),
        "config": e.config or {},
        "enabled": e.enabled,
        "status": e.status,
        "last_tested_at": dt(e.last_tested_at),
        "created_at": dt(e.created_at),
    }
