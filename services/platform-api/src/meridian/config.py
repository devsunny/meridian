from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MERIDIAN_",
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Meridian"
    version: str = "0.1.0"
    env: str = "local"
    service_name: str = "meridian-api"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # Data stores
    database_url: str = "sqlite:///./.data/meridian.db"
    storage_backend: str = "local"  # local | s3
    storage_root: str = "./.data/warehouse"
    log_dir: str = "./.data/logs"
    s3_bucket: str = "meridian"
    s3_prefix: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"

    # Auth
    auth_mode: str = "local"  # local | oidc
    jwt_secret: str = "change-me-in-production-meridian-local-secret"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 480
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    demo_password: str = "Meridian123!"

    # Execution
    worker_poll_seconds: float = 1.0
    scheduler_poll_seconds: float = 5.0
    worker_id: str | None = None
    worker_concurrency: int = 4
    max_ingest_records: int = 200_000
    task_default_timeout_seconds: int = 900
    task_max_attempts: int = 3

    # Security / policy
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    opa_url: str | None = None
    file_roots: str = "./.data"
    login_rate_limit_per_minute: int = 12

    # Observability
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    log_level: str = "INFO"

    # AI
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 45.0

    # Demo
    seed_demo: bool = True
    public_url: str = "http://localhost:3000"

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql://", 1)
        if value.startswith("postgresql://"):
            # psycopg is LGPL; default to the BSD-licensed pure-Python pg8000 driver.
            value = value.replace("postgresql://", "postgresql+pg8000://", 1)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def file_root_list(self) -> list[Path]:
        return [Path(item).expanduser().resolve() for item in self.file_roots.split(",") if item.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def ensure_directories(self) -> None:
        Path(self.storage_root).expanduser().mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).expanduser().mkdir(parents=True, exist_ok=True)
        if self.is_sqlite:
            db_path = self.database_url.replace("sqlite:///", "", 1)
            if db_path and db_path != ":memory:":
                Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def reset_settings_cache() -> None:
    """Test hook: re-read environment variables."""
    get_settings.cache_clear()


# Convenience for module-level defaults; runtime code should use get_settings().
settings = get_settings()


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
