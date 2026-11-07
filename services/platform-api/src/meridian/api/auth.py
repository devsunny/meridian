from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..api.deps import client_ip
from ..audit import write_audit
from ..config import get_settings
from ..context import request_id_var, tenant_id_var, user_id_var
from ..db import get_session
from ..logging_setup import get_logger
from ..models import Tenant
from ..schemas import LoginRequest
from ..security import Principal, authenticate, create_access_token, get_principal
from ..serializers import dt

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("meridian.auth")
settings = get_settings()

_attempts: dict[str, list[float]] = defaultdict(list)


def _rate_limited(ip: str) -> bool:
    now = time.time()
    window = [stamp for stamp in _attempts[ip] if now - stamp < 60]
    _attempts[ip] = window
    if len(window) >= settings.login_rate_limit_per_minute:
        return True
    window.append(now)
    return False


@router.get("/config")
def auth_config() -> dict:
    return {
        "auth_mode": settings.auth_mode,
        "issuer": settings.oidc_issuer,
        "demo": settings.env in {"local", "dev", "test"} and settings.auth_mode == "local",
        "demo_accounts": [
            {"email": "admin@meridian.local", "role": "admin", "name": "Avery Chen"},
            {"email": "steward@meridian.local", "role": "steward", "name": "Priya Raman"},
            {"email": "engineer@meridian.local", "role": "engineer", "name": "Noah Williams"},
            {"email": "analyst@meridian.local", "role": "analyst", "name": "Mia Alvarez"},
            {"email": "auditor@meridian.local", "role": "auditor", "name": "Sam Okafor"},
        ],
        "demo_password_hint": "See docs/09-reference-product.md · local demo only",
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_session)) -> dict:
    ip = client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again in a minute.")
    result = authenticate(db, body.email, body.password)
    if not result:
        logger.warning("login_failed", extra={"email_domain": body.email.split("@")[-1], "ip": ip})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    user, tenant_slug = result
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant or tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active.")
    token, expires_in = create_access_token(user, tenant_slug)
    principal = Principal(user=user, tenant_id=user.tenant_id, tenant_slug=tenant_slug)
    tenant_id_var.set(user.tenant_id)
    user_id_var.set(user.id)
    write_audit(
        db,
        tenant_id=user.tenant_id,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        actor_id=user.id,
        actor_email=user.email,
        ip=ip,
        data={"method": "password", "role": user.role},
    )
    db.commit()
    logger.info("login_succeeded", extra={"user_id": user.id, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": principal.as_dict(),
        "request_id": request_id_var.get(),
    }


@router.get("/me")
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_session)) -> dict:
    tenant = db.get(Tenant, principal.tenant_id)
    return {
        **principal.as_dict(),
        "tenant": {"id": tenant.id, "slug": tenant.slug, "name": tenant.name} if tenant else None,
        "last_login_at": dt(principal.user.last_login_at),
        "request_id": request_id_var.get(),
    }


@router.post("/logout")
def logout(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_session)) -> dict:
    write_audit(
        db,
        tenant_id=principal.tenant_id,
        action="auth.logout",
        resource_type="user",
        resource_id=principal.id,
        actor_id=principal.id,
        actor_email=principal.email,
        ip=client_ip(request),
    )
    db.commit()
    return {"ok": True, "request_id": request_id_var.get()}
