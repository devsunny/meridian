from __future__ import annotations

import os
import shutil
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent / ".test-data"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ.update(
    {
        "MERIDIAN_ENV": "test",
        "MERIDIAN_DATABASE_URL": f"sqlite:///{(TEST_ROOT / 'meridian.db').as_posix()}",
        "MERIDIAN_STORAGE_ROOT": str(TEST_ROOT / "warehouse"),
        "MERIDIAN_LOG_DIR": str(TEST_ROOT / "logs"),
        "MERIDIAN_FILE_ROOTS": str(TEST_ROOT),
        "MERIDIAN_SEED_DEMO": "true",
        "MERIDIAN_DEMO_PASSWORD": "Meridian123!",
        "MERIDIAN_JWT_SECRET": "test-secret-not-for-production-please-change-32bytes",
        "MERIDIAN_LOGIN_RATE_LIMIT_PER_MINUTE": "1000",
        "MERIDIAN_OTEL_ENABLED": "false",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from meridian.engine.worker import process_one  # noqa: E402
from meridian.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str = "admin@meridian.local") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Meridian123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client):
    return login(client)


@pytest.fixture(scope="session")
def analyst_headers(client):
    return login(client, "analyst@meridian.local")


def drain(limit: int = 20) -> None:
    for _ in range(limit):
        if not process_one("pytest-worker"):
            return


def find_pipeline(client: TestClient, headers: dict[str, str], name: str = "Customer Revenue Daily") -> dict:
    response = client.get("/api/v1/pipelines", headers=headers)
    assert response.status_code == 200
    for pipeline in response.json():
        if pipeline["name"] == name:
            return pipeline
    raise AssertionError("seed pipeline not found")


def get_run(client: TestClient, headers: dict[str, str], run_id: str) -> dict:
    response = client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()
