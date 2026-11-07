from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .context import tenant_id_var, user_id_var
from .db import get_session
from .models import ApiKey, User

settings = get_settings()
bearer = HTTPBearer(auto_error=False)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "*",
    },
    "steward": {
        "catalog:read",
        "catalog:write",
        "governance:read",
        "governance:write",
        "security:read",
        "sources:read",
        "sources:write",
        "ingestions:read",
        "ingestions:write",
        "pipelines:read",
        "pipelines:write",
        "schedules:read",
        "schedules:write",
        "runs:read",
        "runs:write",
        "integrations:read",
        "integrations:write",
        "assist:use",
        "audit:read",
    },
    "engineer": {
        "catalog:read",
        "catalog:write",
        "sources:read",
        "sources:write",
        "ingestions:read",
        "ingestions:write",
        "pipelines:read",
        "pipelines:write",
        "schedules:read",
        "schedules:write",
        "runs:read",
        "runs:write",
        "integrations:read",
        "integrations:write",
        "assist:use",
    },
    "analyst": {
        "catalog:read",
        "sources:read",
        "ingestions:read",
        "pipelines:read",
        "schedules:read",
        "runs:read",
        "assist:use",
        "governance:read",
    },
    "auditor": {
        "catalog:read",
        "governance:read",
        "audit:read",
        "security:read",
        "sources:read",
        "ingestions:read",
        "pipelines:read",
        "schedules:read",
        "runs:read",
    },
    "viewer": {"catalog:read", "sources:read", "ingestions:read", "pipelines:read", "runs:read"},
}

ROLE_LABELS = {
    "admin": "Platform administrator",
    "steward": "Data steward",
    "engineer": "Data engineer",
    "analyst": "Business analyst",
    "auditor": "Auditor",
    "viewer": "Viewer",
}


@dataclass
class Principal:
    user: User
    tenant_id: str
    tenant_slug: str

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def name(self) -> str:
        return self.user.name

    def has(self, permission: str) -> bool:
        permissions = ROLE_PERMISSIONS.get(self.role, set())
        return "*" in permissions or permission in permissions

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{self.role}' lacks permission '{permission}'.",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.user.id,
            "email": self.user.email,
            "name": self.user.name,
            "role": self.user.role,
            "role_label": ROLE_LABELS.get(self.user.role, self.user.role),
            "tenant_id": self.tenant_id,
            "tenant_slug": self.tenant_slug,
            "permissions": sorted(ROLE_PERMISSIONS.get(self.role, set())),
        }


# ---- passwords -------------------------------------------------------------------------------
PBKDF2_ITERATIONS = 310_000


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


# ---- JWT -------------------------------------------------------------------------------------
def create_access_token(user: User, tenant_slug: str) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_in = settings.jwt_ttl_minutes * 60
    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "tenant_slug": tenant_slug,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iss": "meridian",
        "aud": "meridian-web",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def decode_token(token: str) -> dict[str, Any]:
    if settings.auth_mode == "oidc":
        return _decode_oidc(token)
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="meridian-web",
            issuer="meridian",
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session.") from exc


def _decode_oidc(token: str) -> dict[str, Any]:
    if not settings.oidc_issuer:
        raise HTTPException(status_code=500, detail="OIDC issuer is not configured.")
    try:
        jwks_url = settings.oidc_jwks_url or f"{settings.oidc_issuer.rstrip('/')}/.well-known/jwks.json"
        key_client = jwt.PyJWKClient(jwks_url)
        signing_key = key_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid identity token.") from exc


def _user_from_claims(db: Session, claims: dict[str, Any]) -> tuple[User, str]:
    email = str(claims.get("email") or claims.get("preferred_username") or "").lower()
    tenant_slug = str(claims.get("tenant_slug") or "acme")
    from .models import Tenant

    tenant = db.execute(select(Tenant).where(Tenant.slug == tenant_slug)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=401, detail="Unknown tenant in identity token.")
    user = db.execute(
        select(User).where(User.tenant_id == tenant.id, User.email == email)
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Your identity is valid but you have not been provisioned in Meridian.",
        )
    return user, tenant.slug


def _api_key_user(db: Session, raw_key: str) -> tuple[User, str] | None:
    if not raw_key.startswith("mk_"):
        return None
    prefix = raw_key[:12]
    key = db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalar_one_or_none()
    if not key or key.revoked_at:
        return None
    if key.expires_at:
        expires_at = key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return None
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    if not hmac.compare_digest(key.key_hash, digest):
        return None
    user = db.get(User, key.created_by) if key.created_by else None
    if not user or not user.is_active:
        return None
    from .models import Tenant

    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        return None
    key.last_used_at = datetime.now(UTC)
    return user, tenant.slug


def _principal_from_request(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
    request: Request,
) -> Principal:
    token = credentials.credentials if credentials else request.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token.startswith("mk_"):
        found = _api_key_user(db, token)
        if not found:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        user, tenant_slug = found
    else:
        claims = decode_token(token)
        user, tenant_slug = _user_from_claims(db, claims)
    principal = Principal(user=user, tenant_id=user.tenant_id, tenant_slug=tenant_slug)
    tenant_id_var.set(user.tenant_id)
    user_id_var.set(user.id)
    return principal


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_session),
) -> Principal:
    return _principal_from_request(db, credentials, request)


def require(permission: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        principal.require(permission)
        return principal

    return dependency


def require_any(*permissions: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not any(principal.has(permission) for permission in permissions):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return principal

    return dependency


def authenticate(db: Session, email: str, password: str) -> tuple[User, str] | None:
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return None
    from .models import Tenant

    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        return None
    user.last_login_at = datetime.now(UTC)
    return user, tenant.slug


def user_from_token(db: Session, token: str) -> Principal:
    if token.startswith("mk_"):
        found = _api_key_user(db, token)
        if not found:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        return Principal(user=found[0], tenant_id=found[0].tenant_id, tenant_slug=found[1])
    claims = decode_token(token)
    user, tenant_slug = _user_from_claims(db, claims)
    return Principal(user=user, tenant_id=user.tenant_id, tenant_slug=tenant_slug)


def create_api_key(db: Session, principal: Principal, name: str, expires_days: int = 90) -> tuple[ApiKey, str]:
    raw = "mk_" + secrets.token_urlsafe(32)
    key = ApiKey(
        tenant_id=principal.tenant_id,
        name=name,
        prefix=raw[:12],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes=["*"],
        created_by=principal.id,
        expires_at=datetime.now(UTC) + timedelta(days=expires_days),
    )
    db.add(key)
    db.flush()
    return key, raw


def credential_fingerprint() -> str:
    """Used in audit metadata; never the secret itself."""
    return hashlib.sha256(settings.jwt_secret.encode()).hexdigest()[:12]


_ = (os, Callable)
