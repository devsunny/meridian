# 8. Reference Implementation Layout

> This document turns the design into a repository, a coding model and a first backlog. It is opinionated on
> purpose: consistency across ten services is worth more than local optimisation in each.

---

## 8.1 Repository topology

One monorepo (`meridian/`) with independently deployable services. A monorepo is chosen for atomic cross-cutting
changes (a new event field touches producer, consumer and contract in one PR) and for a single CI definition;
services still build and deploy independently from their own directories.

```text
meridian/
├── services/                     # one directory = one deployable
│   ├── iam/
│   ├── connect/
│   ├── ingest/
│   ├── orchestrate/
│   ├── catalog/
│   ├── govern/
│   ├── configure/
│   ├── audit/
│   ├── notify/
│   └── assist/
├── packages/                     # shared libraries (versioned, semver, no service imports)
│   ├── edp-common/               # tenancy, auth, outbox, errors, pagination, otel, db
│   ├── connector-sdk/            # contracts, runtime helpers, test fixtures
│   ├── edp-testkit/              # factories, testcontainers, contract harness
│   └── edp-client/               # generated Python/TS clients from specs/openapi.yaml
├── connectors/                   # one image per source family
│   ├── s3/  rest/  sftp/  filesystem/  sharepoint/  onedrive/  gdrive/  box/  mcp/  jdbc/  kafka/
├── web/                          # Next.js app (catalog, wizard, runs, governance)
├── cli/                          # `edp` command line
├── specs/                        # OpenAPI, events, JSON schemas (this package)
├── policies/                     # Rego + tests (this package)
├── deploy/                       # compose, Helm charts, k8s manifests, Terraform
├── docs/                         # this package + runbooks
└── tools/                        # codegen, lint rules, migration helpers
```

**Dependency rule:** services depend on `packages/`, never on each other. Cross-service interaction is HTTP or
events only. Enforced by `import-linter` contracts in CI.

---

## 8.2 Service internal layering

Every service is a small hexagonal application. The domain has no framework imports and is testable without a
database.

```text
services/ingest/
├── pyproject.toml
├── Dockerfile
├── migrations/                  # Alembic, one directory per service/schema
│   └── versions/
├── src/edp_ingest/
│   ├── main.py                  # app factory, lifespan, health/ready
│   ├── api/                     # FastAPI routers; request/response models only
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── domain/                  # pure logic: entities, invariants, state machines
│   │   ├── models.py
│   │   ├── services.py
│   │   └── errors.py
│   ├── ports/                   # protocols the domain depends on
│   │   ├── repository.py
│   │   ├── engine.py            # ExecutionPort (Temporal/Argo/local)
│   │   └── events.py
│   ├── adapters/                # implementations of ports
│   │   ├── db.py                # SQLAlchemy repositories
│   │   ├── temporal.py
│   │   ├── outbox.py
│   │   └── clients.py           # connect, catalog, govern, OPA
│   ├── workers/                 # Temporal activities and workflows (if any)
│   └── settings.py              # pydantic-settings, env-driven
└── tests/
    ├── unit/                    # domain only, no I/O
    ├── integration/             # testcontainers: Postgres, Temporal, S3
    └── contract/                # OpenAPI conformance + event schema
```

Layering rules (enforced by CI):

1. `api → domain`, `adapters → ports`, `domain` imports only `domain` and stdlib/typing.
2. No SQL in `api`; no FastAPI types in `domain`.
3. Every port has at most one production adapter and one fake for tests.
4. All external calls go through a port so they can be recorded, retried and traced centrally.

### Service skeleton

```python
# src/edp_ingest/api/routes.py
@router.post("/ingestions/{ingestion_id}/runs", status_code=202)
async def start_run(
    ingestion_id: str,
    body: StartRunRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    principal: Annotated[Principal, Depends(require_scope("runs:execute"))],
    svc: Annotated[IngestionService, Depends(get_service)],
) -> RunResponse:
    decision = await svc.authorize(principal, "ingest", f"ingestion:{ingestion_id}")
    if not decision.allow:
        raise Forbidden(decision.reason)
    run = await svc.start_run(ingestion_id, body, idempotency_key, principal)
    return RunResponse.from_domain(run)
```

```python
# src/edp_ingest/domain/services.py (no framework, no I/O)
class IngestionService:
    def __init__(self, repo: IngestionRepository, engine: ExecutionPort, clock: Clock):
        self._repo, self._engine, self._clock = repo, engine, clock

    async def start_run(self, ingestion_id, req, idempotency_key, principal) -> Run:
        ingestion = await self._repo.get(ingestion_id)
        if ingestion.status is not Status.ACTIVE:
            raise IngestionNotActive(ingestion_id)
        key = req.logical_date or self._clock.today()
        existing = await self._repo.find_run(ingestion_id, idempotency_key)
        if existing and not req.force:
            return existing                      # idempotent replay
        run = Run.create(ingestion, key, principal, force=req.force)
        await self._repo.add(run)
        await self._engine.start(run)            # port: Temporal | Argo | Local
        return run
```

---

## 8.3 Shared packages

| Package | Contents | Rules |
|---|---|---|
| `edp-common` | `TenantContext`, `Principal`, `require_scope`, `Problem` errors, cursor pagination, outbox, SQLAlchemy base, OTel setup, structured logging, `Clock` | No domain logic; semver; breaking change = major |
| `connector-sdk` | `Connector` protocol, `RunContext`, `Sink`, `Cursor`, checkpoint helpers, `Resource`, `Schema`, fixture harness | Stable public API; connectors pin a minor version |
| `edp-testkit` | Factories (`a_tenant()`, `a_dataset()`), Postgres/Temporal/S3 containers, recorded-fixture loader, `assert_event_published` | Test-only dependency |
| `edp-client` | Generated from OpenAPI + event schemas | Never hand-edited; CI fails on drift |

**Outbox pattern (in `edp-common`):** every state change writes `outbox(event)` in the same transaction; a relay
polls `FOR UPDATE SKIP LOCKED`, publishes, marks sent. Consumers dedupe on `event.id`. This is the only way
services communicate state changes.

---

## 8.4 Connector layout

```text
connectors/box/
├── pyproject.toml
├── Dockerfile                     # distroless, non-root, signed
├── connector.yaml                 # manifest (see specs/connector-manifest.example.yaml)
├── src/edp_connector_box/
│   ├── connector.py               # implements test/discover/describe/read/acl/classify
│   ├── client.py                  # thin SDK wrapper with retry + rate limit
│   └── mapping.py                 # Box item -> Resource, ACL -> SourceACL
└── tests/
    ├── fixtures/                  # recorded API responses
    └── test_contract.py           # sandbox, resume, ACL, rate-limit cases
```

Every connector is tested against the same suite (`edp-testkit.connector_suite`), so a new connector inherits
resume, checkpoint, rate-limit, ACL and error-mapping tests without writing them.

---

## 8.5 Database changes

- One Alembic history per service, one schema, no cross-schema FKs.
- Migrations are **backwards compatible for one release** (expand → migrate → contract). No destructive change in
  the same deploy that stops using a column.
- Every migration has a rollback path or an explicit `# irreversible:` justification reviewed by the DBA.
- Large tables use `CREATE INDEX CONCURRENTLY`, batched backfills, and are tested against a production-sized
  snapshot before merge.
- Row-level security policy is part of the table migration, not an afterthought; a table without
  `tenant_id` and RLS fails CI (except allowlisted platform-global tables).

---

## 8.6 Contracts

| Contract | Artifact | Gate |
|---|---|---|
| HTTP API | `specs/openapi.yaml` | Breaking change detected by `oasdiff` → major version + approval |
| Events | JSON Schema per type in `specs/schemas/` | Compatibility check in CI; new `vN` on breaking change |
| Config kinds | JSON Schema per kind | `configure` validates before apply |
| Connector | `connector.yaml` manifest | Manifest schema + sandbox test before catalog publish |
| Pipeline spec | JSON Schema | Compiled to Argo at publish; compile errors block |

Generated clients are committed; CI regenerates and fails if the diff is non-empty (`make codegen-check`).

---

## 8.7 Testing strategy

| Layer | Scope | Tooling | Target |
|---|---|---|---|
| Unit | Domain rules, state machines, policy helpers | pytest, hypothesis for state machines | ≥ 80% on `domain/` |
| Contract | API conformance, event compatibility, connector manifest | schemathesis, oasdiff, jsonschema | 100% of endpoints |
| Integration | Repository + engine + storage | testcontainers (Postgres, MinIO, Temporal) | Critical paths per service |
| Policy | Every role × classification × action | `opa test`, table-driven fixtures | 100% branches |
| End-to-end | Wizard → ingest → transform → query → access | Playwright + Compose stack | 10 golden journeys |
| Load | 2× baseline API + 1,000 concurrent runs | k6, Locust | p95 within SLO |
| Chaos | Pod kill, node drain, spot interruption, 429 storm, DB failover | Litmus/Chaos Mesh | No data loss, run resumes |
| Security | Sandbox escape, cross-tenant reads, secret leakage, prompt injection | Custom regression suite | 0 findings |

**Non-negotiable:** a bug found in production gets a failing test in the same PR that fixes it. Cross-tenant
read regressions are treated as Sev-1 with a mandatory postmortem.

---

## 8.8 Local development loop

```bash
# 1. Infrastructure
cd deploy && docker compose up -d

# 2. Platform services (from source, hot reload)
uv run uvicorn edp_iam.main:app --reload --port 8001
uv run uvicorn edp_connect.main:app --reload --port 8002
uv run uvicorn edp_ingest.main:app --reload --port 8003
uv run uvicorn edp_orchestrate.main:app --reload --port 8004
# ... or: uv run python tools/dev.py --all

# 3. Web
cd web && pnpm dev

# 4. Seed demo data
uv run python tools/seed.py --tenants acme,globex --with-samples

# 5. Tests
uv run pytest services/ingest -q
docker run --rm -v "$PWD/policies:/policies" openpolicyagent/opa:latest test /policies -v
```

A developer can run a single service against the shared Compose infrastructure; `tools/dev.py` starts all
services with correct ports and a single OTel collector. The `LocalExecutor` runs pipeline steps as subprocesses
so Argo is not required on a laptop.

---

## 8.9 Definition of done (per service, per feature)

- [ ] OpenAPI updated, generated clients regenerated, contract tests pass
- [ ] Domain logic covered by unit tests; integration test for the happy path and one failure mode
- [ ] Authorization checked at the API **and** at the data access point; policy test added
- [ ] Audit event emitted for every mutation; event schema added if a new event
- [ ] Metrics (RED + one domain metric), traces with `run_id`, structured logs with `tenant_id`
- [ ] Dashboard panel + alert (if user-facing SLO) + runbook section
- [ ] Migration is backwards compatible and tested against a snapshot
- [ ] Feature-flagged if it changes existing behaviour; rollback plan documented
- [ ] Load impact assessed (p95, DB connections, queue depth)
- [ ] Docs updated (this package or service README) and an ADR if a decision changed

---

## 8.10 Starter backlog

Epics are ordered by dependency, not by size. Each epic should produce a demo, not just merged code.

| # | Epic | First stories |
|---|---|---|
| E1 | Landing zone & GitOps | Terraform VPC/EKS/RDS/S3; Argo CD bootstrap; Helm service template; secrets via ESO |
| E2 | Identity & tenancy | Tenant/project model; OIDC login; JWT claims → `Principal`; RLS middleware; 6 roles |
| E3 | Service chassis | `edp-common` (errors, pagination, outbox, OTel); health/ready; audit hook; CI template |
| E4 | Connections | CRUD; secret-ref validation; S3 + REST connectors; test-connection; discovery snapshot |
| E5 | Ingestion v1 | Definition + revision; Temporal workflow; staging → validate → bronze commit; run API + SSE |
| E6 | Catalog v1 | Asset/schema registration; OpenLineage collector; OpenMetadata sync; search index |
| E7 | Query path | Iceberg + Lakekeeper + Trino; first gold table; BI connection guide |
| E8 | Pipelines v1 | Pipeline/version; compile to Argo; execution-bridge; run state machine; retries |
| E9 | Scheduling | Cron/event triggers; catch-up; concurrency; SLA; backfill API |
| E10 | Governance v1 | OPA integration; `/decide`; Trino policies; access requests + approvals; decision log |
| E11 | Experience v1 | Catalog list/detail; ingestion wizard (source → preview → map → schedule); run monitor |
| E12 | Operations v1 | Dashboards, alerts, runbooks; backup/restore; cost labels; quota defaults per tenant |

**Milestone M1 (week 6):** E1–E6 + E11 minimal — a pilot user ingests a REST API and sees it in the catalog.
**Milestone M2 (week 16):** E7–E12 — five tenants, scheduled pipelines, governed access, on-call ready.

---

## 8.11 Engineering standards (short list)

| Topic | Standard |
|---|---|
| Language | Python 3.12, `ruff` + `mypy --strict` on `domain/`; TypeScript `strict` in web |
| Async | `asyncio` everywhere in services; no blocking I/O in request paths |
| IDs | UUIDv7 for entities, ULID for runs/events (sortable, opaque) |
| Time | UTC in storage and APIs; ISO 8601 with `Z`; timezone only at the schedule boundary |
| Money/cost | Decimal, never float; currency explicit |
| Errors | Typed domain errors → RFC 9457 at the edge; never leak stack traces or SQL |
| Logging | JSON only; never log secrets, tokens, PII, or full row payloads |
| Config | Env vars for deployment config; `configure` for tenant config; no config files baked into images |
| Feature flags | OpenFeature; every risky change behind a flag with an owner and an expiry date |
| Dependencies | Renovate, pinned lockfiles, `pip-audit`/`npm audit` in CI, no unmaintained packages |
| Images | Distroless, non-root, signed, SBOM, digest-pinned in GitOps |
| Commits | Conventional commits; PR template requires the requirement ID and test evidence |
