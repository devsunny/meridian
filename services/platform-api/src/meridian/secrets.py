from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from .config import get_settings


class SecretResolutionError(RuntimeError):
    pass


@lru_cache(maxsize=256)
def _resolve_cached(ref: str) -> str:
    """Resolve one secret reference. Values are cached in-process, never persisted."""
    if ref.startswith("env:"):
        name = ref[4:]
        value = os.getenv(name)
        if value is None:
            raise SecretResolutionError(f"Environment secret '{name}' is not set")
        return value
    if ref.startswith("aws-sm:"):
        arn = ref[7:]
        try:
            import boto3

            client = boto3.client("secretsmanager")
            response = client.get_secret_value(SecretId=arn)
            return response.get("SecretString") or ""
        except Exception as exc:  # noqa: BLE001
            raise SecretResolutionError(f"Unable to resolve AWS secret: {exc.__class__.__name__}") from exc
    if ref.startswith("file:"):
        path = ref[5:]
        try:
            return open(path, encoding="utf-8").read().strip()  # noqa: SIM115
        except OSError as exc:
            raise SecretResolutionError(f"Unable to read secret file: {exc.__class__.__name__}") from exc
    raise SecretResolutionError(
        "Unsupported secret reference. Use env:NAME, aws-sm:ARN, or file:/path (mounted secret)."
    )


def resolve_secret(ref: str | None) -> str | None:
    if not ref:
        return None
    return _resolve_cached(ref)


class Resolver:
    """Callable passed to connector contexts."""

    def __call__(self, ref: str | None) -> str | None:
        return resolve_secret(ref)


def collect_secrets(config: dict[str, Any], secret_ref: str | None) -> dict[str, str | None]:
    """Resolve the connection-level ref plus every `<field>_ref` in config."""
    resolved: dict[str, str | None] = {}
    if secret_ref:
        resolved["__connection__"] = resolve_secret(secret_ref)
    for key, value in config.items():
        if key.endswith("_ref") and isinstance(value, str) and value:
            try:
                resolved[key[:-4]] = resolve_secret(value)
            except SecretResolutionError:
                resolved[key[:-4]] = None
    return resolved


def secret_for(config: dict[str, Any], secrets: dict[str, str | None], key: str) -> str | None:
    """Read a secret by logical field name, falling back to the connection-level secret."""
    return secrets.get(key) or secrets.get("__connection__")


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Defensive UI-safe redaction; config should never contain raw secrets."""
    sensitive = ("password", "token", "secret", "key", "credential")
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        if any(marker in key.lower() for marker in sensitive) and not key.endswith(("_ref", "_env")):
            redacted[key] = "***" if value else value
        else:
            redacted[key] = value
    return redacted


def get_settings_secret() -> str:
    return get_settings().jwt_secret
