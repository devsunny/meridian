# Meridian Platform API

FastAPI control plane for the Meridian reference product. The same Python package runs in three
roles:

| Role | Entry point | Responsibility |
|---|---|---|
| `api` | `meridian.main:app` | REST/SSE/WebSocket control plane, UI BFF |
| `scheduler` | `python -m meridian.engine.scheduler` | materialises due schedules into DAG runs |
| `worker` | `python -m meridian.engine.worker` | leases and executes tasks from the distributed queue |

All roles are stateless and horizontally scalable. Metadata lives in PostgreSQL; the queue uses
`FOR UPDATE SKIP LOCKED`. The local profile defaults to SQLite and local object storage so the
product can be evaluated without Docker.
