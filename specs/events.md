# Event Contract

> CloudEvents 1.0 over an internal bus (SNS/SQS or Kafka, phase 3). Producers write to a transactional outbox in
> the same database transaction as the state change; a relay publishes. Consumers are idempotent on `id`.

---

## 1. Envelope

```json
{
  "specversion": "1.0",
  "id": "01J8Z9K3T7Q2M4X9B6C1D5E8FA",
  "source": "edp.ingest",
  "type": "io.edp.ingestion.run.succeeded.v1",
  "subject": "tenants/acme/ingestions/ing_123/runs/run_456",
  "time": "2026-10-31T06:14:03.221Z",
  "datacontenttype": "application/json",
  "dataschema": "https://schemas.edp.example/ingestion.run.succeeded/v1.json",
  "tenantid": "acme",
  "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "idempotencykey": "ing_123:2026-10-31",
  "data": { }
}
```

| Extension | Required | Meaning |
|---|---|---|
| `tenantid` | yes | Isolation and routing |
| `traceparent` | yes | W3C trace context for end-to-end tracing |
| `idempotencykey` | yes for state-changing events | Natural key for dedupe |
| `actor` | when human-initiated | `{"type":"user","id":"u_123"}` |
| `correlationid` | when part of a larger operation | E.g. a backfill id |
| `schemaVersion` | in `type` suffix | `v1`; breaking changes → `v2` |

**Delivery semantics:** at-least-once, ordered per `subject` where the broker allows. Consumers must be
idempotent. Retries: 5 attempts with exponential backoff + jitter, then DLQ with replay tooling.

**Schema evolution:** additive fields only within a version; consumers ignore unknown fields; a breaking change
requires a new `type` (`...v2`) and dual-publish for 30 days.

---

## 2. Event catalog

### Identity and tenancy (`edp.iam`)

| Type | Payload highlights |
|---|---|
| `io.edp.tenant.created.v1` | `tenant_id`, `slug`, `isolation_tier`, `region` |
| `io.edp.user.provisioned.v1` | `user_id`, `email`, `groups[]` |
| `io.edp.user.deprovisioned.v1` | `user_id`, `reason` — triggers grant revocation |
| `io.edp.role.binding.changed.v1` | `principal`, `role`, `scope`, `added|removed` |

### Connectivity (`edp.connect`)

| Type | Payload highlights |
|---|---|
| `io.edp.connection.created.v1` / `.updated.v1` / `.deleted.v1` | `connection_id`, `type`, `owner` |
| `io.edp.connection.tested.v1` | `connection_id`, `ok`, `latency_ms`, `error_code` |
| `io.edp.connection.discovered.v1` | `connection_id`, `snapshot_id`, `resource_count` |
| `io.edp.connection.auth.expiring.v1` | `connection_id`, `expires_at`, `days_left` |

### Ingestion (`edp.ingest`)

| Type | Payload highlights |
|---|---|
| `io.edp.ingestion.created.v1` / `.updated.v1` | `ingestion_id`, `revision`, `target_urn` |
| `io.edp.ingestion.run.started.v1` | `run_id`, `ingestion_id`, `logical_date` |
| `io.edp.ingestion.run.progress.v1` | `run_id`, `bytes`, `records`, `percent` |
| `io.edp.ingestion.run.succeeded.v1` | `run_id`, `dataset_version`, `bytes`, `records`, `duration_s` |
| `io.edp.ingestion.run.failed.v1` | `run_id`, `error_code`, `retryable`, `details_uri` |
| `io.edp.ingestion.run.quarantined.v1` | `run_id`, `violations[]`, `quarantine_uri` |

### Catalog (`edp.catalog`)

| Type | Payload highlights |
|---|---|
| `io.edp.dataset.created.v1` | `urn`, `layer`, `owner`, `classification` |
| `io.edp.dataset.version.created.v1` | `urn`, `version`, `schema_hash`, `row_count`, `snapshot_id` |
| `io.edp.dataset.schema.changed.v1` | `urn`, `from`, `to`, `breaking`, `changes[]` |
| `io.edp.dataset.quality.failed.v1` | `urn`, `run_id`, `checks[]` |
| `io.edp.dataset.freshness.sla.missed.v1` | `urn`, `sla`, `last_updated` |
| `io.edp.lineage.edge.created.v1` | `from_urn`, `to_urn`, `job_urn`, `column_map` |
| `io.edp.asset.classified.v1` | `urn`, `column`, `tag`, `confidence`, `source` |
| `io.edp.document.indexed.v1` | `document_id`, `chunks`, `embedding_model`, `acl_hash` |

### Orchestration (`edp.orchestrate`)

| Type | Payload highlights |
|---|---|
| `io.edp.pipeline.version.published.v1` | `pipeline_id`, `version`, `spec_hash`, `author` |
| `io.edp.schedule.triggered.v1` | `schedule_id`, `logical_date`, `trigger` |
| `io.edp.pipeline.run.started.v1` | `run_id`, `pipeline_id`, `version`, `data_interval` |
| `io.edp.pipeline.run.succeeded.v1` | `run_id`, `duration_s`, `tasks[]`, `cost_estimate` |
| `io.edp.pipeline.run.failed.v1` | `run_id`, `failed_task`, `error_code`, `retryable` |
| `io.edp.pipeline.run.sla.missed.v1` | `run_id`, `deadline`, `overrun_s` |
| `io.edp.backfill.completed.v1` | `backfill_id`, `runs`, `failed` |

### Governance (`edp.govern`)

| Type | Payload highlights |
|---|---|
| `io.edp.policy.changed.v1` | `policy_id`, `version`, `bundle_hash` — invalidate all decision caches |
| `io.edp.access.request.submitted.v1` / `.approved.v1` / `.denied.v1` | `request_id`, `resource_urn`, `requester`, `approver` |
| `io.edp.grant.created.v1` / `.revoked.v1` | `grant_id`, `principal`, `resource_urn`, `expires_at` |
| `io.edp.classification.override.v1` | `asset_id`, `column`, `from`, `to`, `steward` |

### Configuration (`edp.configure`)

| Type | Payload highlights |
|---|---|
| `io.edp.config.applied.v1` | `kind`, `name`, `revision`, `environment` |
| `io.edp.config.drift.detected.v1` | `kind`, `name`, `git_hash`, `live_hash` |
| `io.edp.feature_flag.changed.v1` | `key`, `tenant_id`, `enabled` |

### Usage (`edp.usage`)

| Type | Payload highlights |
|---|---|
| `io.edp.usage.threshold.reached.v1` | `tenant_id`, `period`, `percent`, `budget` |

---

## 3. Webhook subscriptions

```http
POST /v1/subscriptions
{
  "url": "https://hooks.acme.example/edp",
  "types": ["io.edp.pipeline.run.failed.v1", "io.edp.dataset.freshness.sla.missed.v1"],
  "secretRef": "arn:aws:secretsmanager:us-east-1:123:secret:webhook/acme",
  "filters": { "labels.domain": "finance" }
}
```

Headers on delivery: `X-EDP-Signature: t=<unix>,v1=<hmac-sha256(t + "." + body)>`, `X-EDP-Delivery`,
`X-EDP-Event-Type`. Receivers must verify the signature and tolerate duplicates (dedupe on `id`). Replay window
30 days via `POST /v1/subscriptions/{id}:replay`.

---

## 4. Internal topics / queues

| Topic | Producer | Consumer | Ordering key |
|---|---|---|---|
| `edp.state.changes` | all services (outbox relay) | catalog sync, search indexer, notify, audit | `subject` |
| `edp.runs` | orchestrate | UI SSE, notify, usage-meter | `run_id` |
| `edp.lineage` | connectors, Spark, dbt, Trino | lineage-collector | `run_id` |
| `edp.audit` | all services | audit writer, SIEM exporter | `tenant_id` |
| `edp.connector.tasks` | orchestrate | connector workers (KEDA) | `connection_id` |
| `edp.document.tasks` | ingest | doc-processor workers (KEDA) | `document_id` |
| `edp.dlq.*` | consumers | ops tooling | — |

---

## 5. Anti-patterns

- Publishing before the transaction commits (use the outbox).
- Using events as a database (consumers must be able to rebuild from the API).
- Unbounded payloads (cap at 256 KB; put bulk data in S3 and reference the URI).
- Consumer-side ordering assumptions without a partition key.
- Emitting PII in payloads — reference the asset, never inline the data.
