from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .context import new_id, utcnow
from .db import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


def _id(prefix: str) -> str:
    return new_id(prefix)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("ten"))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="active")
    isolation_tier: Mapped[str] = mapped_column(String(24), default="shared")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("usr"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(240), index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default="analyst")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_connections_tenant_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("con"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(48), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active")
    owner: Mapped[str] = mapped_column(String(160), default="")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_datasets_tenant_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("ds"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    layer: Mapped[str] = mapped_column(String(16), default="raw")
    format: Mapped[str] = mapped_column(String(24), default="jsonl")
    classification: Mapped[str] = mapped_column(String(24), default="internal")
    owner: Mapped[str] = mapped_column(String(160), default="")
    location: Mapped[str] = mapped_column(String(1000), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)
    schema_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    source_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_uri: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("dsv"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(1000))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    schema_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LineageEdge(Base):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint("tenant_id", "from_dataset_id", "to_dataset_id", "job_run_id", name="uq_lineage_edge"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("lin"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    from_dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    to_dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    job_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    operation: Mapped[str] = mapped_column(String(80), default="transform")
    request_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ingestion(Base):
    __tablename__ = "ingestions"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ingestions_tenant_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("ing"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"), index=True)
    target_dataset: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schedule_timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    status: Mapped[str] = mapped_column(String(24), default="active")
    owner: Mapped[str] = mapped_column(String(160), default="")
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_pipelines_tenant_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("pip"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(24), default="active")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    dag: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"
    __table_args__ = (UniqueConstraint("pipeline_id", "version", name="uq_pipeline_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("piv"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    dag: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_by: Mapped[str] = mapped_column(String(160), default="")
    request_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("sch"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    target_type: Mapped[str] = mapped_column(String(24))  # pipeline | ingestion
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    cron: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    catchup: Mapped[bool] = mapped_column(Boolean, default=False)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, default=1)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency"),
        Index("ix_job_runs_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("run"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # ingestion | pipeline
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    request_id: Mapped[str] = mapped_column(String(80), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(300))
    logical_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    debug: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(160), default="")
    schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (
        UniqueConstraint("job_run_id", "task_id", name="uq_task_run_job_task"),
        Index("ix_task_runs_queue", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("task"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    job_run_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(48), index=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    depends_on: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=900)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    request_id: Mapped[str] = mapped_column(String(80), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debug_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("job_run_id", "seq", name="uq_run_event_seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("evt"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    job_run_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(48), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    request_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "seq", name="uq_audit_tenant_seq"),
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("aud"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(64), default="system")
    actor_email: Mapped[str] = mapped_column(String(240), default="system")
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(120), default="")
    outcome: Mapped[str] = mapped_column(String(24), default="success")
    request_id: Mapped[str] = mapped_column(String(80), index=True)
    ip: Mapped[str] = mapped_column(String(80), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("ar"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    requester_id: Mapped[str] = mapped_column(String(64), index=True)
    requester_email: Mapped[str] = mapped_column(String(240))
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(24), default="read")
    purpose: Mapped[str] = mapped_column(Text, default="")
    duration_days: Mapped[int] = mapped_column(Integer, default=7)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessGrant(Base):
    __tablename__ = "access_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("gr"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    principal_id: Mapped[str] = mapped_column(String(64), index=True)
    principal_email: Mapped[str] = mapped_column(String(240))
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(24), default="read")
    request_id_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granted_by: Mapped[str] = mapped_column(String(160), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_chunks_tenant_dataset", "tenant_id", "dataset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("chk"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    source_uri: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(500), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    classification: Mapped[str] = mapped_column(String(24), default="internal")
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalSystem(Base):
    __tablename__ = "external_systems"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_external_system_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("ext"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(32))  # airflow | dbt_cloud | fivetran | airbyte | webhook
    base_url: Mapped[str] = mapped_column(String(1000), default="")
    secret_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="configured")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("key"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_by: Mapped[str] = mapped_column(String(160), default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("upl"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    path: Mapped[str] = mapped_column(String(1000))
    size: Mapped[int] = mapped_column(Integer, default=0)
    media_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# Silence unused import warnings for uuid in type checking contexts.
_ = (uuid, Float, Text)
