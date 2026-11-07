from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..context import request_id_var
from ..db import get_session
from ..models import ApiKey, User
from ..schemas import ApiKeyCreate, UserCreate, UserUpdate
from ..security import (
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    Principal,
    create_api_key,
    hash_password,
    require,
)
from ..serializers import dt
from .deps import admin_count, client_ip, get_or_404

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/users")
def list_users(
    principal: Principal = Depends(require("security:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(select(User).where(User.tenant_id == principal.tenant_id).order_by(User.created_at.asc()))
        .scalars()
        .all()
    )
    return [
        {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "role_label": ROLE_LABELS.get(user.role, user.role),
            "is_active": user.is_active,
            "last_login_at": dt(user.last_login_at),
            "created_at": dt(user.created_at),
        }
        for user in rows
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    principal: Principal = Depends(require("security:write")),
    db: Session = Depends(get_session),
) -> dict:
    existing = db.execute(
        select(User).where(User.tenant_id == principal.tenant_id, User.email == body.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    temporary_password = body.password or secrets.token_urlsafe(12)
    entity = User(
        tenant_id=principal.tenant_id,
        email=body.email,
        name=body.name,
        role=body.role,
        password_hash=hash_password(temporary_password),
    )
    db.add(entity)
    db.flush()
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="user.created",
        resource_type="user",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"email": entity.email, "role": entity.role},
    )
    db.commit()
    return {
        "user": {
            "id": entity.id,
            "email": entity.email,
            "name": entity.name,
            "role": entity.role,
            "is_active": entity.is_active,
        },
        "temporary_password": temporary_password if not body.password else None,
        "request_id": request_id_var.get(),
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    principal: Principal = Depends(require("security:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, User, user_id, principal.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    if (
        changes.get("role")
        and entity.role == "admin"
        and changes["role"] != "admin"
        and admin_count(db, principal.tenant_id) <= 1
    ):
        raise HTTPException(status_code=409, detail="Cannot demote the last active administrator.")
    if changes.get("is_active") is False and entity.id == principal.id:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account.")
    for key, value in changes.items():
        setattr(entity, key, value)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="user.updated",
        resource_type="user",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"fields": sorted(changes), "role": entity.role},
    )
    db.commit()
    return {
        "id": entity.id,
        "email": entity.email,
        "name": entity.name,
        "role": entity.role,
        "is_active": entity.is_active,
        "request_id": request_id_var.get(),
    }


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    request: Request,
    principal: Principal = Depends(require("security:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity = get_or_404(db, User, user_id, principal.tenant_id)
    temporary_password = secrets.token_urlsafe(12)
    entity.password_hash = hash_password(temporary_password)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="user.password_reset",
        resource_type="user",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()
    return {
        "user_id": entity.id,
        "temporary_password": temporary_password,
        "request_id": request_id_var.get(),
    }


@router.get("/roles")
def roles(principal: Principal = Depends(require("security:read"))) -> dict:
    return {
        "roles": [
            {
                "name": role,
                "label": ROLE_LABELS.get(role, role),
                "permissions": sorted(permissions),
            }
            for role, permissions in ROLE_PERMISSIONS.items()
        ],
        "request_id": request_id_var.get(),
    }


@router.get("/overview")
def security_overview(
    principal: Principal = Depends(require("security:read")), db: Session = Depends(get_session)
) -> dict:
    users = (
        db.execute(select(User).where(User.tenant_id == principal.tenant_id)).scalars().all()
    )
    keys = (
        db.execute(
            select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id, ApiKey.revoked_at.is_(None))
        )
        .scalars()
        .all()
    )
    return {
        "users": len(users),
        "active_users": len([user for user in users if user.is_active]),
        "admins": len([user for user in users if user.role == "admin" and user.is_active]),
        "active_api_keys": len(keys),
        "auth_mode": __import__("meridian.config", fromlist=["get_settings"]).get_settings().auth_mode,
        "request_id": request_id_var.get(),
    }


@router.get("/api-keys")
def list_api_keys(
    principal: Principal = Depends(require("security:read")), db: Session = Depends(get_session)
) -> list[dict]:
    rows = (
        db.execute(
            select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id).order_by(ApiKey.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": key.id,
            "name": key.name,
            "prefix": key.prefix,
            "scopes": key.scopes,
            "last_used_at": dt(key.last_used_at),
            "expires_at": dt(key.expires_at),
            "revoked_at": dt(key.revoked_at),
            "created_at": dt(key.created_at),
        }
        for key in rows
    ]


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
def issue_api_key(
    body: ApiKeyCreate,
    request: Request,
    principal: Principal = Depends(require("security:write")),
    db: Session = Depends(get_session),
) -> dict:
    entity, raw = create_api_key(db, principal, body.name, body.expires_days)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="api_key.created",
        resource_type="api_key",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
        data={"name": entity.name, "prefix": entity.prefix, "expires_at": dt(entity.expires_at)},
    )
    db.commit()
    return {
        "id": entity.id,
        "name": entity.name,
        "prefix": entity.prefix,
        "key": raw,
        "expires_at": dt(entity.expires_at),
        "notice": "Copy this key now. It is not stored in plaintext and cannot be shown again.",
        "request_id": request_id_var.get(),
    }


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(require("security:write")),
    db: Session = Depends(get_session),
) -> None:
    entity = get_or_404(db, ApiKey, key_id, principal.tenant_id)
    entity.revoked_at = datetime.now(UTC)
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="api_key.revoked",
        resource_type="api_key",
        resource_id=entity.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()
