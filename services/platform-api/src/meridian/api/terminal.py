from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..config import get_settings
from ..context import new_request_id, request_context
from ..db import SessionLocal
from ..engine.dag import create_pipeline_run
from ..logging_setup import RunJsonlLogger
from ..models import Connection, Dataset, JobRun, Pipeline
from ..security import user_from_token
from ..serializers import run as serialize_run

router = APIRouter(tags=["terminal"])
settings = get_settings()

HELP = """Meridian remote terminal (restricted)
  help                     show this help
  whoami                   identity, role and tenant
  sources                  list configured sources
  datasets                 list governed datasets
  runs [n]                 recent runs
  logs <run_id> [n]        run JSONL logs
  run <pipeline name|id>    start a pipeline (requires runs:write)
  ask <question>           governed RAG assistant
  clear                    clear the terminal
  exit                     close the session
This is an application shell, not a host shell. Commands are tenant-scoped and audited."""


def _fmt(value: str) -> str:
    return value.replace("\n", "\r\n")


@router.websocket("/ws/terminal")
async def terminal(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    await websocket.accept()
    if not token:
        await websocket.send_text("Authentication required. Sign in and reopen the terminal.\r\n")
        await websocket.close(code=4401)
        return
    with SessionLocal() as db:
        try:
            principal = user_from_token(db, token)
        except Exception:  # noqa: BLE001
            await websocket.send_text("Invalid or expired session.\r\n")
            await websocket.close(code=4401)
            return
    await websocket.send_text(
        _fmt(
            "\x1b[1;36mMeridian remote terminal\x1b[0m\r\n"
            f"Connected as {principal.email} · {principal.role} · tenant {principal.tenant_slug}\r\n"
            "Type 'help' for application commands. Host shell is intentionally disabled.\r\n\r\n"
        )
    )
    try:
        while True:
            raw = await websocket.receive_text()
            command = raw.strip()[:4000]
            if not command:
                continue
            rid = new_request_id()
            with request_context(request_id=rid, tenant_id=principal.tenant_id, user_id=principal.id):
                if command in {"exit", "quit"}:
                    await websocket.send_text("Closing session.\r\n")
                    await websocket.close()
                    return
                if command == "clear":
                    await websocket.send_text("\x1b[2J\x1b[H")
                    continue
                if command == "help":
                    await websocket.send_text(_fmt(HELP) + "\r\n")
                    continue
                try:
                    output = _dispatch(command, principal, rid)
                except Exception as exc:  # noqa: BLE001
                    output = f"error: {exc.__class__.__name__}: {exc}"
                await websocket.send_text(_fmt(output) + f"\r\n\x1b[2mrequest_id={rid}\x1b[0m\r\n\r\n")
    except WebSocketDisconnect:
        return


def _dispatch(command: str, principal, request_id: str) -> str:
    from .deps import can_read_data

    parts = command.split(maxsplit=1)
    verb = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    with SessionLocal() as db:
        if verb == "whoami":
            return json.dumps(
                {
                    "email": principal.email,
                    "role": principal.role,
                    "tenant": principal.tenant_slug,
                    "tenant_id": principal.tenant_id,
                    "permissions": sorted(principal.as_dict()["permissions"]),
                },
                indent=2,
            )
        if verb == "sources":
            rows = (
                db.execute(select(Connection).where(Connection.tenant_id == principal.tenant_id))
                .scalars()
                .all()
            )
            return "\n".join(f"{row.id}  {row.type:<12} {row.name}  [{row.status}]" for row in rows) or "No sources."
        if verb == "datasets":
            rows = (
                db.execute(
                    select(Dataset)
                    .where(Dataset.tenant_id == principal.tenant_id)
                    .order_by(Dataset.updated_at.desc())
                    .limit(100)
                )
                .scalars()
                .all()
            )
            return (
                "\n".join(
                    f"{row.id}  {row.layer:<7} {row.classification:<13} {row.row_count:>8} rows  {row.name}"
                    + ("" if can_read_data(db, row, principal) else "  [access request required]")
                    for row in rows
                )
                or "No datasets."
            )
        if verb == "runs":
            limit = int(argument) if argument.isdigit() else 15
            rows = (
                db.execute(
                    select(JobRun)
                    .where(JobRun.tenant_id == principal.tenant_id)
                    .order_by(JobRun.created_at.desc())
                    .limit(min(limit, 50))
                )
                .scalars()
                .all()
            )
            return "\n".join(
                f"{row.id}  {row.kind:<9} {row.status:<10} {row.created_at.isoformat() if row.created_at else ''}  req={row.request_id}"
                for row in rows
            ) or "No runs."
        if verb == "logs":
            tokens = argument.split()
            if not tokens:
                return "usage: logs <run_id> [lines]"
            job = db.get(JobRun, tokens[0])
            if not job or job.tenant_id != principal.tenant_id:
                return "run not found"
            limit = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 200
            entries = RunJsonlLogger(settings.log_dir, job.tenant_id, job.id).read(limit=min(limit, 1000))
            return "\n".join(json.dumps(entry, default=str) for entry in entries) or "No logs yet."
        if verb == "run":
            if not argument:
                return "usage: run <pipeline name|id>"
            if not principal.has("runs:write"):
                return "permission denied: runs:write"
            pipeline = db.get(Pipeline, argument)
            if not pipeline or pipeline.tenant_id != principal.tenant_id:
                pipeline = db.execute(
                    select(Pipeline).where(
                        Pipeline.tenant_id == principal.tenant_id, Pipeline.name.ilike(f"%{argument}%")
                    )
                ).scalars().first()
            if not pipeline:
                return "pipeline not found"
            job = create_pipeline_run(
                db,
                pipeline,
                request_id=request_id,
                created_by=principal.email,
                trigger="terminal",
            )
            db.commit()
            return f"started {job.id} status={job.status}\n{json.dumps(serialize_run(job), indent=2, default=str)}"
        if verb == "ask":
            if not argument:
                return "usage: ask <question>"
            from ..services.assistant import ask as ask_assistant
            from .deps import accessible_dataset_ids

            allowed = accessible_dataset_ids(db, principal.tenant_id, principal)
            result = ask_assistant(db, principal.tenant_id, argument, allowed, 5, allowed_dataset_ids=allowed)
            citations = "\n".join(
                f"[{item['index']}] {item['title']} p.{item['page'] or '-'}" for item in result["citations"]
            )
            db.commit()
            return f"{result['answer']}\n\nCitations:\n{citations or 'none'}"
        return f"Unknown command: {verb}. Type 'help'."
