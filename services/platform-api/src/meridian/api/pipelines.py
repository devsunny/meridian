from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..engine.dag import create_pipeline_run
from ..models import JobRun, Pipeline, PipelineVersion
from ..schemas import DagSpec, PipelineCreate, PipelineUpdate, RunCreate
from ..security import Principal, require
from ..serializers import dt, pipeline, run
from .deps import client_ip, get_or_404

router = APIRouter(tags=["pipelines"])

TASK_TYPES = [
    {
        "type": "ingestion.run",
        "label": "Run ingestion",
        "category": "source",
        "description": "Execute a configured ingestion and land a dataset.",
        "fields": [{"name": "ingestion_id", "label": "Ingestion", "type": "ingestion"}],
    },
    {
        "type": "sql.transform",
        "label": "SQL transform",
        "category": "transform",
        "description": "DuckDB SQL over one or more upstream datasets. Use the `input` view.",
        "fields": [
            {"name": "sql", "label": "SQL", "type": "sql"},
            {"name": "target_dataset", "label": "Target dataset", "type": "dataset"},
            {"name": "layer", "label": "Layer", "type": "layer", "default": "silver"},
        ],
    },
    {
        "type": "quality.check",
        "label": "Quality gate",
        "category": "quality",
        "description": "Fail the DAG when row, null or uniqueness expectations are not met.",
        "fields": [
            {"name": "min_rows", "label": "Minimum rows", "type": "integer", "default": 1},
            {"name": "required_columns", "label": "Required columns", "type": "list"},
            {"name": "max_null_pct", "label": "Max null %", "type": "number"},
            {"name": "unique_column", "label": "Unique column", "type": "string"},
        ],
    },
    {
        "type": "http.request",
        "label": "HTTP request",
        "category": "action",
        "description": "Call an allowlisted external HTTP endpoint.",
        "fields": [
            {"name": "url", "label": "URL", "type": "string"},
            {"name": "method", "label": "Method", "type": "select", "options": ["GET", "POST", "PUT", "PATCH"]},
            {"name": "body", "label": "JSON body", "type": "json"},
        ],
    },
    {
        "type": "etl.trigger",
        "label": "Trigger external ETL",
        "category": "integration",
        "description": "Trigger Airflow, dbt Cloud, Fivetran, Airbyte or a generic webhook.",
        "fields": [{"name": "external_system_id", "label": "External system", "type": "integration"}],
    },
    {
        "type": "ai.generate",
        "label": "AI / RAG task",
        "category": "ai",
        "description": "Ask a governed question over upstream document datasets.",
        "fields": [
            {"name": "prompt", "label": "Prompt", "type": "textarea"},
            {"name": "top_k", "label": "Passages", "type": "integer", "default": 6},
        ],
    },
    {
        "type": "approval",
        "label": "Human approval",
        "category": "control",
        "description": "Pause the run until an authorised user approves.",
        "fields": [{"name": "message", "label": "Message", "type": "textarea"}],
    },
    {
        "type": "notify",
        "label": "Notify",
        "category": "action",
        "description": "Emit a notification run event.",
        "fields": [{"name": "message", "label": "Message", "type": "textarea"}],
    },
    {
        "type": "noop",
        "label": "No-op",
        "category": "control",
        "description": "A placeholder task useful while designing the DAG.",
        "fields": [],
    },
]


@router.get("/pipelines/task-types")
def task_types(principal: Principal = Depends(require("pipelines:read"))) -> list[dict]:
    return TASK_TYPES


@router.get("/pipelines/templates")
def templates(principal: Principal = Depends(require("pipelines:read"))) -> list[dict]:
    return [
        {
            "id": "medallion",
            "name": "Medallion ingestion → quality → gold",
            "description": "Land a source, clean it with SQL, enforce a quality gate, then publish a gold aggregate.",
            "dag": {
                "nodes": [
                    {
                        "id": "land",
                        "name": "Land source",
                        "type": "ingestion.run",
                        "config": {"ingestion_id": ""},
                        "position": {"x": 60, "y": 180},
                    },
                    {
                        "id": "clean",
                        "name": "Clean & conform",
                        "type": "sql.transform",
                        "config": {
                            "sql": "SELECT * FROM input WHERE 1=1",
                            "target_dataset": "silver_clean",
                            "layer": "silver",
                        },
                        "position": {"x": 340, "y": 180},
                    },
                    {
                        "id": "gate",
                        "name": "Quality gate",
                        "type": "quality.check",
                        "config": {"min_rows": 1},
                        "position": {"x": 620, "y": 180},
                    },
                    {
                        "id": "gold",
                        "name": "Publish gold",
                        "type": "sql.transform",
                        "config": {
                            "sql": "SELECT * FROM input",
                            "target_dataset": "gold_publish",
                            "layer": "gold",
                        },
                        "position": {"x": 900, "y": 180},
                    },
                ],
                "edges": [
                    {"source": "land", "target": "clean"},
                    {"source": "clean", "target": "gate"},
                    {"source": "gate", "target": "gold"},
                ],
            },
        },
        {
            "id": "parallel",
            "name": "Parallel enrichment",
            "description": "Fan out two transforms and merge them with a final SQL step.",
            "dag": {
                "nodes": [
                    {"id": "land", "name": "Land", "type": "ingestion.run", "config": {}, "position": {"x": 60, "y": 160}},
                    {
                        "id": "enrich_a",
                        "name": "Enrich A",
                        "type": "sql.transform",
                        "config": {"sql": "SELECT * FROM input", "target_dataset": "silver_a", "layer": "silver"},
                        "position": {"x": 340, "y": 60},
                    },
                    {
                        "id": "enrich_b",
                        "name": "Enrich B",
                        "type": "sql.transform",
                        "config": {"sql": "SELECT * FROM input", "target_dataset": "silver_b", "layer": "silver"},
                        "position": {"x": 340, "y": 280},
                    },
                    {
                        "id": "merge",
                        "name": "Merge",
                        "type": "sql.transform",
                        "config": {"sql": "SELECT * FROM input", "target_dataset": "gold_merged", "layer": "gold"},
                        "position": {"x": 640, "y": 160},
                    },
                ],
                "edges": [
                    {"source": "land", "target": "enrich_a"},
                    {"source": "land", "target": "enrich_b"},
                    {"source": "enrich_a", "target": "merge"},
                    {"source": "enrich_b", "target": "merge"},
                ],
            },
        },
    ]


@router.post("/pipelines/validate")
def validate_dag(body: DagSpec, principal: Principal = Depends(require("pipelines:read"))) -> dict:
    return {"valid": True, "dag": body.to_dict(), "nodes": len(body.nodes), "request_id": request_id_var.get()}


@router.get("/pipelines")
def list_pipelines(
    principal: Principal = Depends(require("pipelines:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(
            select(Pipeline)
            .where(Pipeline.tenant_id == principal.tenant_id, Pipeline.status != "archived")
            .order_by(Pipeline.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [pipeline(row) for row in rows]


@router.post("/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline(
    body: PipelineCreate,
    request: Request,
    principal: Principal = Depends(require("pipelines:write")),
    db: Session = Depends(get_session),
) -> dict:
    existing = db.execute(
        select(Pipeline).where(Pipeline.tenant_id == principal.tenant_id, Pipeline.name == body.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A pipeline with this name already exists.")
    entity = Pipeline(
        tenant_id=principal.tenant_id,
        name=body.name,
        description=body.description,
        owner=body.owner or principal.email,
        current_version=1,
        dag=body.dag.to_dict(),
    )
    db.add(entity)
    db.flush()
    db.add(
        PipelineVersion(
            tenant_id=principal.tenant_id,
            pipeline_id=entity.id,
            version=1,
            dag=entity.dag,
            created_by=principal.email,
            request_id=request_id_var.get(),
        )
    )
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="pipeline.created",
        resource_type="pipeline",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"nodes": len(body.dag.nodes), "version": 1},
    )
    db.commit()
    return pipeline(entity)


@router.get("/pipelines/{pipeline_id}")
def get_pipeline(
    pipeline_id: str,
    principal: Principal = Depends(require("pipelines:read")),
    db: Session = Depends(get_session),
) -> dict:
    return pipeline(get_or_404(db, Pipeline, pipeline_id, principal.tenant_id))


@router.patch("/pipelines/{pipeline_id}")
def update_pipeline(
    pipeline_id: str,
    body: PipelineUpdate,
    request: Request,
    principal: Principal = Depends(require("pipelines:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Pipeline, pipeline_id, principal.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    new_dag = changes.pop("dag", None)
    for key, value in changes.items():
        setattr(entity, key, value)
    if new_dag is not None:
        entity.current_version += 1
        entity.dag = new_dag
        db.add(
            PipelineVersion(
                tenant_id=principal.tenant_id,
                pipeline_id=entity.id,
                version=entity.current_version,
                dag=new_dag,
                created_by=principal.email,
                request_id=request_id_var.get(),
            )
        )
    entity.updated_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="pipeline.updated",
        resource_type="pipeline",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"fields": sorted([*changes, *(["dag"] if new_dag else [])]), "version": entity.current_version},
    )
    db.commit()
    return pipeline(entity)


@router.post("/pipelines/{pipeline_id}/validate")
def validate_pipeline(
    pipeline_id: str,
    principal: Principal = Depends(require("pipelines:read")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Pipeline, pipeline_id, principal.tenant_id)
    try:
        dag = DagSpec.model_validate(entity.dag)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return {"valid": True, "nodes": len(dag.nodes), "dag": dag.to_dict(), "request_id": request_id_var.get()}


@router.delete("/pipelines/{pipeline_id}", status_code=204)
def archive_pipeline(
    pipeline_id: str,
    request: Request,
    principal: Principal = Depends(require("pipelines:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, Pipeline, pipeline_id, principal.tenant_id)
    entity.status = "archived"
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="pipeline.archived",
        resource_type="pipeline",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()


@router.get("/pipelines/{pipeline_id}/versions")
def pipeline_versions(
    pipeline_id: str,
    principal: Principal = Depends(require("pipelines:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    entity = get_or_404(db, Pipeline, pipeline_id, principal.tenant_id)
    rows = (
        db.execute(
            select(PipelineVersion)
            .where(PipelineVersion.pipeline_id == entity.id)
            .order_by(PipelineVersion.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "version": row.version,
            "created_by": row.created_by,
            "created_at": dt(row.created_at),
            "nodes": len((row.dag or {}).get("nodes", [])),
        }
        for row in rows
    ]


@router.post("/pipelines/{pipeline_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_pipeline(
    pipeline_id: str,
    body: RunCreate,
    request: Request,
    principal: Principal = Depends(require("runs:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, Pipeline, pipeline_id, principal.tenant_id)
    if entity.status != "active":
        raise HTTPException(status_code=409, detail="Pipeline is not active.")
    try:
        job = create_pipeline_run(
            db,
            entity,
            request_id=request_id_var.get(),
            created_by=principal.email,
            trigger="manual",
            debug=body.debug,
            logical_date=body.logical_date,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="run.started",
        resource_type="pipeline_run",
        resource_id=job.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"pipeline_id": entity.id, "version": entity.current_version, "debug": body.debug, "request_id": job.request_id},
    )
    db.commit()
    return run(job)


@router.get("/pipelines/{pipeline_id}/runs")
def pipeline_runs(
    pipeline_id: str,
    limit: int = 25,
    principal: Principal = Depends(require("runs:read")),
    db: Session = Depends(get_session),
) -> list[dict]:
    entity = get_or_404(db, Pipeline, pipeline_id, principal.tenant_id)
    rows = (
        db.execute(
            select(JobRun)
            .where(JobRun.tenant_id == principal.tenant_id, JobRun.target_id == entity.id, JobRun.kind == "pipeline")
            .order_by(JobRun.created_at.desc())
            .limit(min(limit, 100))
        )
        .scalars()
        .all()
    )
    return [run(row) for row in rows]
