from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..context import request_id_var
from ..db import db_health, get_session
from ..security import Principal, get_principal
from ..serializers import dt
from ..services.datasets import tenant_dashboard

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/dashboard")
def dashboard(principal: Principal = Depends(get_principal), db: Session = Depends(get_session)) -> dict:
    data = tenant_dashboard(db, principal.tenant_id)
    data["request_id"] = request_id_var.get()
    data["role"] = principal.role
    return data


@router.get("/system/info")
def system_info(principal: Principal = Depends(get_principal)) -> dict:
    db_ok, db_message = db_health()
    return {
        "name": settings.app_name,
        "version": settings.version,
        "environment": settings.env,
        "service": settings.service_name,
        "request_id": request_id_var.get(),
        "auth_mode": settings.auth_mode,
        "storage_backend": settings.storage_backend,
        "otel_enabled": settings.otel_enabled,
        "database": {"ok": db_ok, "message": db_message},
        "features": {
            "connectors": True,
            "dag_orchestration": True,
            "scheduler": True,
            "remote_debugger": True,
            "web_terminal": True,
            "assist": True,
            "soc2_audit_chain": True,
            "external_etl": True,
        },
        "user": principal.email,
    }


@router.get("/schedules/upcoming")
def upcoming(principal: Principal = Depends(get_principal), db: Session = Depends(get_session)) -> list[dict]:
    from sqlalchemy import select

    from ..models import Schedule

    schedules = (
        db.execute(
            select(Schedule)
            .where(Schedule.tenant_id == principal.tenant_id, Schedule.enabled.is_(True))
            .order_by(Schedule.next_run_at.asc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": schedule.id,
            "name": schedule.name,
            "cron": schedule.cron,
            "timezone": schedule.timezone,
            "next_run_at": dt(schedule.next_run_at),
            "target_type": schedule.target_type,
        }
        for schedule in schedules
    ]
