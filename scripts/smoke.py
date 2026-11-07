"""Local smoke test: login, run the seeded pipeline, execute work, verify outputs.

Usage (from the repository root):
    uv run --project services/platform-api python scripts/smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from meridian.engine.worker import process_one  # noqa: E402
from meridian.main import app  # noqa: E402


def main() -> int:
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@meridian.local", "password": "Meridian123!"},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-Request-ID": "req_smoke_test_000001"}
        dashboard = client.get("/api/v1/dashboard", headers=headers)
        dashboard.raise_for_status()
        print("tenant:", dashboard.json()["tenant"]["name"])
        print("datasets:", dashboard.json()["counts"]["datasets"])
        pipelines = client.get("/api/v1/pipelines", headers=headers).json()
        if not pipelines:
            print("no pipeline found", file=sys.stderr)
            return 1
        pipeline = pipelines[0]
        response = client.post(f"/api/v1/pipelines/{pipeline['id']}/run", headers=headers, json={"debug": False})
        response.raise_for_status()
        run_id = response.json()["id"]
        print("started run:", run_id, response.json()["request_id"])
        for _ in range(12):
            if not process_one("smoke-worker"):
                break
        detail = client.get(f"/api/v1/runs/{run_id}", headers=headers)
        detail.raise_for_status()
        payload = detail.json()
        print("run status:", payload["status"])
        for task in payload["tasks"]:
            print(f"  {task['task_id']:<18} {task['status']:<10} {task['error'] or ''}")
        logs = client.get(f"/api/v1/runs/{run_id}/logs", headers=headers).json()["entries"]
        print("jsonl log entries:", len(logs))
        datasets = client.get("/api/v1/datasets", headers=headers).json()
        print("datasets after run:", [item["name"] for item in datasets])
        citations = client.post(
            "/api/v1/assist/ask",
            headers=headers,
            json={"question": "What is the refund approval threshold for a support lead?", "top_k": 3},
        )
        citations.raise_for_status()
        print("assist mode:", citations.json()["mode"], "citations:", len(citations.json()["citations"]))
        return 0 if payload["status"] == "SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
