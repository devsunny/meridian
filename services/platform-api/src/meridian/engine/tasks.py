from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..logging_setup import get_logger
from ..models import Dataset, ExternalSystem, Ingestion, JobRun, Pipeline, TaskRun
from ..secrets import resolve_secret
from ..services.assistant import ask as ask_assistant
from ..services.datasets import add_lineage
from ..services.ingestion import execute_ingestion
from ..services.transforms import run_quality_checks, transform_sql

logger = get_logger("meridian.tasks")
settings = get_settings()


class TaskPaused(RuntimeError):
    """Raised by a handler that requires a human decision."""


class TaskFailure(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class TaskResult:
    output: dict[str, Any]
    metrics: dict[str, Any]


Handler = Callable[[Session, JobRun, TaskRun], TaskResult]


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", value.lower()).strip("_")[:180]


def _dataset_for_task(session: Session, run: JobRun, task_id: str) -> Dataset | None:
    upstream = session.execute(
        select(TaskRun).where(TaskRun.job_run_id == run.id, TaskRun.task_id == task_id)
    ).scalar_one_or_none()
    if not upstream:
        return None
    dataset_id = (upstream.output or {}).get("dataset_id")
    if not dataset_id:
        return None
    return session.get(Dataset, dataset_id)


def _input_datasets(session: Session, run: JobRun, task: TaskRun) -> list[tuple[str, Dataset]]:
    inputs: list[tuple[str, Dataset]] = []
    for dependency in task.depends_on or []:
        dataset = _dataset_for_task(session, run, dependency)
        if dataset and dataset.tenant_id == run.tenant_id:
            inputs.append((dependency, dataset))
    return inputs


def handle_ingestion(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    ingestion_id = task.spec.get("ingestion_id")
    ingestion = session.get(Ingestion, ingestion_id) if ingestion_id else None
    if not ingestion or ingestion.tenant_id != run.tenant_id:
        raise TaskFailure("The ingestion referenced by this task no longer exists.", retryable=False)
    output = execute_ingestion(
        session,
        ingestion,
        request_id=run.request_id,
        run_id=run.id,
        max_records=task.spec.get("_max_records"),
    )
    return TaskResult(output=output, metrics={"rows": output["rows"], "bytes": output["bytes"]})


def handle_transform(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    inputs = _input_datasets(session, run, task)
    if not inputs:
        raise TaskFailure("No upstream dataset is available for this transform.", retryable=False)
    pipeline = session.get(Pipeline, run.target_id)
    target = task.spec.get("target_dataset") or task.spec.get("target")
    if not target:
        target = _safe_name(f"{pipeline.name if pipeline else 'pipeline'}_{task.task_id}")
    target = _safe_name(str(target))
    layer = str(task.spec.get("layer") or "silver")
    sql = str(task.spec.get("sql") or "")
    dataset, rows = transform_sql(
        session,
        tenant_id=run.tenant_id,
        inputs=inputs,
        sql=sql,
        target_name=target,
        layer=layer,
        run_id=run.id,
        request_id=run.request_id,
        owner=pipeline.owner if pipeline else "",
    )
    for _, source in inputs:
        add_lineage(
            session,
            tenant_id=run.tenant_id,
            from_dataset_id=source.id,
            to_dataset_id=dataset.id,
            run_id=run.id,
            task_id=task.task_id,
            operation="sql.transform",
            request_id=run.request_id,
        )
    return TaskResult(
        output={
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "dataset_version": dataset.version,
            "rows": rows,
            "columns": len(dataset.schema_json or []),
        },
        metrics={"rows": rows},
    )


def handle_quality(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    inputs = _input_datasets(session, run, task)
    if not inputs:
        raise TaskFailure("No upstream dataset is available for quality checks.", retryable=False)
    dataset = inputs[0][1]
    result = run_quality_checks(
        dataset,
        min_rows=int(task.spec.get("min_rows", 1)),
        required_columns=list(task.spec.get("required_columns") or []),
        max_null_pct=float(task.spec["max_null_pct"]) if task.spec.get("max_null_pct") is not None else None,
        unique_column=task.spec.get("unique_column"),
    )
    if not result["passed"]:
        raise TaskFailure("Quality gate failed: " + "; ".join(result["failures"]), retryable=False)
    return TaskResult(output={"dataset_id": dataset.id, **result}, metrics={})


def handle_http(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    url = str(task.spec.get("url") or "")
    if not url.startswith(("http://", "https://")):
        raise TaskFailure("URL must use http or https.", retryable=False)
    method = str(task.spec.get("method") or "GET").upper()
    headers = dict(task.spec.get("headers") or {})
    headers["X-Request-ID"] = run.request_id
    token = resolve_secret(task.spec.get("token_ref")) if task.spec.get("token_ref") else None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=float(task.spec.get("timeout_seconds", 30))) as client:
            response = client.request(method, url, headers=headers, json=task.spec.get("body"))
    except httpx.HTTPError as exc:
        raise TaskFailure(f"HTTP request failed: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        raise TaskFailure(
            f"HTTP request returned {response.status_code}.",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
    return TaskResult(
        output={
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body_preview": response.text[:2000],
        },
        metrics={},
    )


def handle_etl(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    system_ref = task.spec.get("external_system_id") or task.spec.get("external_system")
    system = session.get(ExternalSystem, system_ref) if system_ref else None
    if system is None and system_ref:
        system = session.execute(
            select(ExternalSystem).where(
                ExternalSystem.tenant_id == run.tenant_id, ExternalSystem.name == system_ref
            )
        ).scalar_one_or_none()
    if not system or system.tenant_id != run.tenant_id or not system.enabled:
        raise TaskFailure("External ETL system is missing, disabled or belongs to another tenant.", retryable=False)
    token = resolve_secret(system.secret_ref)
    config = {**(system.config or {}), **(task.spec.get("config") or {})}
    base = system.base_url.rstrip("/")
    headers = {"Content-Type": "application/json", "X-Request-ID": run.request_id}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = base
    body: dict[str, Any] = {}
    if system.type == "airflow":
        dag_id = config.get("dag_id") or task.spec.get("dag_id")
        if not dag_id:
            raise TaskFailure("Airflow integration requires dag_id.", retryable=False)
        url = f"{base}/api/v1/dags/{dag_id}/dagRuns"
        body = {"dag_run_id": f"meridian_{run.id}", "conf": task.spec.get("conf") or {}}
    elif system.type == "dbt_cloud":
        account_id = config.get("account_id")
        job_id = config.get("job_id") or task.spec.get("job_id")
        if not account_id or not job_id:
            raise TaskFailure("dbt Cloud integration requires account_id and job_id.", retryable=False)
        url = f"{base}/api/v2/accounts/{account_id}/jobs/{job_id}/run/"
        body = {"cause": f"Meridian run {run.id}", "extra": {"meridian_run_id": run.id}}
        if token:
            headers["Authorization"] = f"Token {token}"
    elif system.type == "fivetran":
        connector_id = config.get("connector_id") or task.spec.get("connector_id")
        if not connector_id:
            raise TaskFailure("Fivetran integration requires connector_id.", retryable=False)
        url = f"{base}/v1/connectors/{connector_id}/sync"
        body = {}
        if token:
            headers["Authorization"] = f"Basic {token}"
    elif system.type == "airbyte":
        connection_id = config.get("connection_id") or task.spec.get("connection_id")
        if not connection_id:
            raise TaskFailure("Airbyte integration requires connection_id.", retryable=False)
        url = f"{base}/api/v1/connections/sync"
        body = {"connectionId": connection_id}
    else:
        body = {"run_id": run.id, "pipeline_id": run.target_id, "request_id": run.request_id, **config.get("payload", {})}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise TaskFailure(f"External ETL call failed: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        raise TaskFailure(
            f"{system.type} returned HTTP {response.status_code}.",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
    return TaskResult(
        output={
            "external_system": system.name,
            "provider": system.type,
            "status": response.status_code,
            "response": response.text[:2000],
        },
        metrics={},
    )


def handle_approval(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    raise TaskPaused(str(task.spec.get("message") or "Manual approval is required before this task can run."))


def handle_notify(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    channel = str(task.spec.get("channel") or "run-event")
    message = str(task.spec.get("message") or f"Pipeline {run.target_id} reached {task.task_id}.")
    logger.info("notification", extra={"channel": channel, "message": message, "run_id": run.id})
    return TaskResult(output={"channel": channel, "message": message, "delivered": True}, metrics={})


def handle_ai(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    prompt = str(task.spec.get("prompt") or "")
    if not prompt:
        raise TaskFailure("AI task requires a prompt.", retryable=False)
    dataset_ids = list(task.spec.get("dataset_ids") or [])
    for _, dataset in _input_datasets(session, run, task):
        dataset_ids.append(dataset.id)
    result = ask_assistant(session, run.tenant_id, prompt, dataset_ids, int(task.spec.get("top_k", 6)))
    return TaskResult(
        output={
            "answer": result["answer"],
            "mode": result["mode"],
            "citations": result["citations"],
            "model": result["model"],
        },
        metrics={"citations": len(result["citations"])},
    )


def handle_noop(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    return TaskResult(output={"ok": True, "message": "No-op task completed."}, metrics={})


HANDLERS: dict[str, Handler] = {
    "ingestion.run": handle_ingestion,
    "sql.transform": handle_transform,
    "quality.check": handle_quality,
    "http.request": handle_http,
    "etl.trigger": handle_etl,
    "approval": handle_approval,
    "notify": handle_notify,
    "ai.generate": handle_ai,
    "noop": handle_noop,
}


def execute_task(session: Session, run: JobRun, task: TaskRun) -> TaskResult:
    handler = HANDLERS.get(task.type)
    if not handler:
        raise TaskFailure(f"Unsupported task type '{task.type}'.", retryable=False)
    started = time.perf_counter()
    result = handler(session, run, task)
    result.metrics.setdefault("duration_seconds", round(time.perf_counter() - started, 3))
    return result
