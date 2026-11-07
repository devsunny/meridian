from __future__ import annotations

from .conftest import drain, find_pipeline, get_run


def test_health_and_request_id(client):
    response = client.get("/health/live", headers={"X-Request-ID": "req_contract_test_0001"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req_contract_test_0001"
    assert response.json()["status"] == "ok"


def test_login_and_rbac(client, analyst_headers):
    me = client.get("/api/v1/auth/me", headers=analyst_headers)
    assert me.status_code == 200
    assert me.json()["role"] == "analyst"
    denied = client.post(
        "/api/v1/pipelines",
        headers=analyst_headers,
        json={"name": "Analyst pipeline", "description": "", "dag": {"nodes": [], "edges": []}},
    )
    assert denied.status_code == 403


def test_dag_validation_rejects_cycle(client, admin_headers):
    response = client.post(
        "/api/v1/pipelines/validate",
        headers=admin_headers,
        json={
            "nodes": [
                {"id": "a", "type": "noop", "config": {}, "depends_on": ["b"]},
                {"id": "b", "type": "noop", "config": {}, "depends_on": ["a"]},
            ],
            "edges": [],
        },
    )
    assert response.status_code == 422


def test_seeded_pipeline_end_to_end(client, admin_headers):
    pipeline = find_pipeline(client, admin_headers)
    response = client.post(f"/api/v1/pipelines/{pipeline['id']}/run", headers=admin_headers, json={"debug": False})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert response.json()["request_id"] == response.headers["x-request-id"]
    drain()
    run = get_run(client, admin_headers, run_id)
    assert run["status"] == "SUCCEEDED", run
    assert all(task["status"] == "SUCCEEDED" for task in run["tasks"])
    assert run["request_id"] == response.json()["request_id"]
    logs = client.get(f"/api/v1/runs/{run_id}/logs", headers=admin_headers)
    assert logs.status_code == 200
    entries = logs.json()["entries"]
    assert entries
    assert all(entry.get("request_id") for entry in entries)
    catalog = client.get("/api/v1/datasets", headers=admin_headers).json()
    names = {item["name"] for item in catalog}
    assert {"sales_orders_raw", "silver_sales_orders", "gold_sales_summary"} <= names


def test_debug_breakpoint_pause_and_resume(client, admin_headers):
    pipeline = find_pipeline(client, admin_headers)
    dag = pipeline["dag"]
    for node in dag["nodes"]:
        node["breakpoint"] = node["id"] == "clean_orders"
    updated = client.patch(f"/api/v1/pipelines/{pipeline['id']}", headers=admin_headers, json={"dag": dag})
    assert updated.status_code == 200, updated.text
    response = client.post(f"/api/v1/pipelines/{pipeline['id']}/run", headers=admin_headers, json={"debug": True})
    assert response.status_code == 202
    run_id = response.json()["id"]
    drain()
    run = get_run(client, admin_headers, run_id)
    assert run["status"] == "PAUSED", run
    paused = [task for task in run["tasks"] if task["status"] == "PAUSED"]
    assert len(paused) == 1
    assert paused[0]["task_id"] == "clean_orders"
    assert paused[0]["breakpoint"] is True
    resumed = client.post(f"/api/v1/runs/{run_id}/resume", headers=admin_headers, json={"task_id": "clean_orders", "note": "test"})
    assert resumed.status_code == 200, resumed.text
    drain()
    run = get_run(client, admin_headers, run_id)
    assert run["status"] == "SUCCEEDED", run


def test_restricted_data_requires_grant(client, admin_headers, analyst_headers):
    datasets = client.get("/api/v1/datasets", headers=analyst_headers).json()
    restricted = next(item for item in datasets if item["name"] == "customer_pii_master")
    assert restricted["can_read"] is False
    denied = client.get(f"/api/v1/datasets/{restricted['id']}/preview", headers=analyst_headers)
    assert denied.status_code == 403
    requests = client.get("/api/v1/governance/access-requests", headers=admin_headers).json()
    pending = next(item for item in requests if item["dataset_id"] == restricted["id"] and item["status"] == "PENDING")
    approved = client.post(
        f"/api/v1/governance/access-requests/{pending['id']}/approve",
        headers=admin_headers,
        json={"reason": "pytest approval"},
    )
    assert approved.status_code == 200, approved.text
    allowed = client.get(f"/api/v1/datasets/{restricted['id']}/preview?limit=3", headers=analyst_headers)
    assert allowed.status_code == 200, allowed.text
    assert len(allowed.json()["rows"]) == 3


def test_timestamps_are_utc_and_date_columns_are_not_phone_pii(client, admin_headers):
    datasets = client.get("/api/v1/datasets", headers=admin_headers).json()
    sales = next(item for item in datasets if item["name"] == "sales_orders_raw")
    detail = client.get(f"/api/v1/datasets/{sales['id']}", headers=admin_headers).json()
    date_column = next(column for column in detail["schema"] if column["name"] == "order_date")
    assert date_column["pii"] is False
    assert detail["updated_at"].endswith("Z")


def test_api_key_authentication(client, admin_headers):
    issued = client.post(
        "/api/v1/security/api-keys",
        headers=admin_headers,
        json={"name": "pytest-key", "expires_days": 1},
    )
    assert issued.status_code == 201, issued.text
    key = issued.json()["key"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {key}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "admin@meridian.local"


def test_audit_chain_and_assistant(client, admin_headers):
    verify = client.get("/api/v1/governance/audit/verify", headers=admin_headers)
    assert verify.status_code == 200
    assert verify.json()["valid"] is True
    answer = client.post(
        "/api/v1/assist/ask",
        headers=admin_headers,
        json={"question": "What is the refund approval threshold for a support lead?", "top_k": 3},
    )
    assert answer.status_code == 200, answer.text
    payload = answer.json()
    assert payload["citations"]
    assert "500" in payload["answer"] or "2,500" in payload["answer"]
