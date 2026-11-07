from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TASK_TYPES = {
    "ingestion.run",
    "sql.transform",
    "quality.check",
    "http.request",
    "etl.trigger",
    "approval",
    "notify",
    "ai.generate",
    "noop",
}

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _.\-]{1,158}$")
TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")


class LoginRequest(BaseModel):
    email: str
    password: str


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    type: str = Field(min_length=2, max_length=48)
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not NAME_RE.match(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore.")
        return value.strip()


class ConnectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    secret_ref: str | None = None
    status: str | None = None


class IngestionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = ""
    connection_id: str
    target_dataset: str = Field(min_length=2, max_length=200)
    spec: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str | None = None
    schedule_timezone: str = "UTC"
    owner: str = ""

    @field_validator("target_dataset")
    @classmethod
    def normalize_target(cls, value: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_]{1,198}$", value):
            raise ValueError("Target dataset must be lowercase letters, numbers and underscores.")
        return value


class IngestionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_dataset: str | None = None
    spec: dict[str, Any] | None = None
    schedule_cron: str | None = None
    schedule_timezone: str | None = None
    status: str | None = None
    owner: str | None = None


class DagNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str | None = None
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    position: dict[str, float] | None = None
    breakpoint: bool = False
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not TASK_ID_RE.match(value):
            raise ValueError("Task id must start with a letter and contain letters, numbers, _ or -.")
        return value

    @field_validator("type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in TASK_TYPES:
            raise ValueError(f"Unsupported task type '{value}'. Allowed: {', '.join(sorted(TASK_TYPES))}")
        return value


class DagEdge(BaseModel):
    source: str
    target: str


class DagSpec(BaseModel):
    nodes: list[DagNode] = Field(default_factory=list, max_length=100)
    edges: list[DagEdge] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def validate_graph(self) -> DagSpec:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Task ids must be unique.")
        known = set(ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"Edge references unknown task: {edge.source} -> {edge.target}")
        # Derive dependencies from edges, preserving explicit dependencies.
        derived: dict[str, set[str]] = {node.id: set(node.depends_on) for node in self.nodes}
        for edge in self.edges:
            derived[edge.target].add(edge.source)
        for node in self.nodes:
            for dependency in derived[node.id]:
                if dependency not in known:
                    raise ValueError(f"Task '{node.id}' depends on unknown task '{dependency}'.")
            node.depends_on = sorted(derived[node.id])
        _assert_acyclic(ids, derived)
        if not ids:
            raise ValueError("A DAG must contain at least one task.")
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def _assert_acyclic(ids: list[str], dependencies: dict[str, set[str]]) -> None:
    indegree = {node: 0 for node in ids}
    children: dict[str, list[str]] = {node: [] for node in ids}
    for node, deps in dependencies.items():
        indegree[node] = len(deps)
        for dep in deps:
            children[dep].append(node)
    queue = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(ids):
        raise ValueError("The DAG contains a cycle.")


class PipelineCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = ""
    owner: str = ""
    dag: DagSpec

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not NAME_RE.match(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore.")
        return value.strip()


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    owner: str | None = None
    status: str | None = None
    dag: DagSpec | None = None


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    target_type: Literal["pipeline", "ingestion"]
    target_id: str
    cron: str
    timezone: str = "UTC"
    enabled: bool = True
    catchup: bool = False
    max_concurrent_runs: int = Field(default=1, ge=1, le=20)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        from croniter import croniter

        if not croniter.is_valid(value):
            raise ValueError("Invalid 5-field cron expression.")
        return value


class ScheduleUpdate(BaseModel):
    name: str | None = None
    cron: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    catchup: bool | None = None
    max_concurrent_runs: int | None = Field(default=None, ge=1, le=20)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from croniter import croniter

        if not croniter.is_valid(value):
            raise ValueError("Invalid 5-field cron expression.")
        return value


class RunCreate(BaseModel):
    debug: bool = False
    force: bool = False
    logical_date: datetime | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class AccessRequestCreate(BaseModel):
    dataset_id: str
    action: Literal["read", "query", "export"] = "read"
    purpose: str = Field(min_length=4, max_length=2000)
    duration_days: int = Field(default=7, ge=1, le=90)


class AccessDecision(BaseModel):
    reason: str = ""


class UserCreate(BaseModel):
    email: str
    name: str
    role: str
    password: str | None = Field(default=None, min_length=10)

    @field_validator("email")
    @classmethod
    def email_lower(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("A valid email is required.")
        return value.lower()

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        allowed = {"admin", "steward", "engineer", "analyst", "auditor", "viewer"}
        if value not in allowed:
            raise ValueError(f"Role must be one of {', '.join(sorted(allowed))}")
        return value


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    type: Literal["airflow", "dbt_cloud", "fivetran", "airbyte", "webhook"]
    base_url: str
    secret_ref: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class IntegrationUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    secret_ref: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class AssistRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    dataset_ids: list[str] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=6, ge=1, le=20)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    expires_days: int = Field(default=90, ge=1, le=365)


class DebugAction(BaseModel):
    task_id: str | None = None
    note: str = ""


class ApprovalAction(BaseModel):
    task_id: str
    approve: bool = True
    note: str = ""


class QueryRequest(BaseModel):
    dataset_id: str
    sql: str = Field(min_length=8, max_length=20_000)
    limit: int = Field(default=100, ge=1, le=1000)
