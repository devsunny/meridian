# Domain Model (operational database)

> Postgres 16. One schema per service; no cross-schema foreign keys (IDs are logical references). Every table has
> `tenant_id` (except platform-global tables), `created_at`, `updated_at`, `revision` (optimistic concurrency),
> and is protected by row-level security keyed on `current_setting('edp.tenant_id')`.

---

## 1. Schemas and key tables

### `iam`

| Table | Key columns | Notes |
|---|---|---|
| `tenant` | `id`, `slug`, `name`, `isolation_tier`, `region`, `status`, `kms_key_arn` | `isolation_tier ∈ shared, isolated, dedicated` |
| `project` | `id`, `tenant_id`, `slug`, `name`, `domain`, `cost_center` | Unit of collaboration and quota |
| `app_user` | `id`, `tenant_id`, `email`, `display_name`, `idp_subject`, `status` | Synced from IdP via SCIM/OIDC |
| `group` | `id`, `tenant_id`, `name`, `source` (`idp`, `platform`) | Mirrors IdP groups |
| `group_member` | `group_id`, `user_id` | |
| `role_binding` | `id`, `tenant_id`, `principal_type`, `principal_id`, `role`, `scope_type`, `scope_id`, `expires_at` | RBAC grant; `scope_*` points to tenant/project/domain |
| `service_account` | `id`, `tenant_id`, `name`, `scopes`, `expires_at`, `last_used_at` | Never a human; must expire |

### `connect`

| Table | Key columns | Notes |
|---|---|---|
| `connection` | `id`, `tenant_id`, `name`, `type`, `config` (jsonb), `credential_ref`, `owner`, `status`, `last_tested_at` | `config` holds non-secret settings; `credential_ref` is an ARN |
| `connection_health` | `connection_id`, `checked_at`, `latency_ms`, `ok`, `error_code` | Last 30 days, partitioned by day |
| `discovery_snapshot` | `id`, `connection_id`, `run_id`, `captured_at`, `resource_count`, `object_uri` | Full snapshot lives in S3; row is the index |
| `source_resource` | `id`, `connection_id`, `external_id`, `path`, `kind`, `size`, `mtime`, `etag`, `acl_hash`, `metadata` (jsonb) | Current known state |
| `source_acl` | `resource_id`, `principal`, `principal_type`, `permission` | Snapshot from source; drives ACL mapping |

### `ingest`

| Table | Key columns | Notes |
|---|---|---|
| `ingestion` | `id`, `tenant_id`, `name`, `connection_id`, `spec` (jsonb), `target_dataset_id`, `owner`, `status`, `current_revision` | `spec` validated against JSON Schema |
| `ingestion_revision` | `ingestion_id`, `revision`, `spec`, `spec_hash`, `author`, `created_at` | Immutable |
| `ingestion_run` | `id`, `ingestion_id`, `run_key`, `logical_date`, `status`, `started_at`, `ended_at`, `bytes`, `records`, `error_code`, `temporal_workflow_id` | `run_key` unique per ingestion |
| `ingestion_checkpoint` | `ingestion_id`, `resource_id`, `cursor` (jsonb), `watermark`, `updated_at` | Resume point |
| `validation_result` | `run_id`, `check`, `severity`, `passed`, `observed`, `expected`, `sample_uri` | |

### `orchestrate`

| Table | Key columns | Notes |
|---|---|---|
| `pipeline` | `id`, `tenant_id`, `project_id`, `name`, `owner`, `status`, `current_version` | |
| `pipeline_version` | `pipeline_id`, `version`, `spec` (jsonb), `spec_hash`, `compiled_argo_ref`, `created_at` | Immutable; content-addressed |
| `job_definition` | `id`, `pipeline_version_id`, `task_id`, `type`, `spec` (jsonb), `priority`, `timeout_s`, `retry_policy` | One per DAG node |
| `schedule` | `id`, `pipeline_id`, `kind` (`cron`, `rate`, `event`, `dependency`), `expression`, `timezone`, `catchup`, `concurrency`, `sla`, `status`, `next_run_at` | |
| `job_run` | `id`, `job_definition_id`, `pipeline_version_id`, `logical_date`, `data_interval_start/end`, `status`, `idempotency_key`, `trigger`, `created_at`, `started_at`, `ended_at`, `attempt_count`, `cost_estimate` | `idempotency_key` unique |
| `attempt` | `id`, `job_run_id`, `number`, `status`, `engine_ref`, `started_at`, `ended_at`, `exit_code`, `error_code` | |
| `task_run` | `id`, `job_run_id`, `task_id`, `status`, `attempt`, `pod_name`, `log_uri`, `metrics` (jsonb) | |
| `run_event` | `id`, `job_run_id`, `seq`, `type`, `payload` (jsonb), `at` | Append-only; source for SSE |
| `backfill` | `id`, `pipeline_id`, `range_start`, `range_end`, `max_parallel`, `status`, `created_by` | Groups child runs |
| `quota` | `tenant_id`, `quota_class`, `cpu`, `memory`, `gpu`, `max_concurrent_runs` | Mirrors Kueue |

### `catalog`

| Table | Key columns | Notes |
|---|---|---|
| `asset` | `id`, `tenant_id`, `urn`, `kind` (`dataset`, `document`, `dashboard`, `model`, `topic`), `name`, `domain`, `owner`, `steward`, `classification`, `criticality`, `lifecycle_state`, `om_id` | `urn` globally unique |
| `dataset` | `asset_id`, `layer` (`raw`,`bronze`,`silver`,`gold`,`sandbox`), `format`, `location`, `partition_spec`, `iceberg_table_id` | |
| `schema_version` | `id`, `asset_id`, `version`, `columns` (jsonb), `schema_hash`, `created_at` | `columns`: name, type, nullable, pii, classification, description |
| `contract` | `id`, `asset_id`, `version`, `spec` (jsonb), `status`, `approved_by` | |
| `contract_violation` | `contract_id`, `run_id`, `column`, `kind`, `observed`, `severity`, `at` | |
| `quality_result` | `id`, `asset_id`, `run_id`, `check`, `severity`, `passed`, `observed`, `expected`, `at` | |
| `lineage_edge` | `id`, `tenant_id`, `from_urn`, `to_urn`, `job_urn`, `run_id`, `column_map` (jsonb), `observed_at`, `source` (`connector`,`spark`,`dbt`,`trino`,`manual`) | Unique on `(from_urn,to_urn,job_urn,run_id)` |
| `document` | `asset_id`, `source_uri`, `mime_type`, `content_hash`, `pages`, `language`, `extracted_uri`, `chunk_count`, `acl_hash` | |
| `chunk` | `id`, `document_id`, `seq`, `text_uri`, `tokens`, `section_path`, `embedding_model`, `vector_id`, `pii_spans` (jsonb) | Vectors live in OpenSearch |
| `glossary_term` | `id`, `tenant_id`, `name`, `definition`, `owner`, `om_id` | Mirrors OM |
| `asset_tag` | `asset_id`, `tag`, `source`, `confidence`, `evidence_uri`, `set_by`, `expires_at` | |

### `govern`

| Table | Key columns | Notes |
|---|---|---|
| `policy` | `id`, `tenant_id`, `name`, `kind` (`rbac`,`abac`,`mask`,`row_filter`), `rego`, `version`, `status`, `approved_by` | Source is Git; DB is a mirror for UI |
| `classification` | `id`, `tenant_id`, `asset_id`, `column`, `tag`, `source`, `confidence`, `evidence`, `reviewed_by` | |
| `access_request` | `id`, `tenant_id`, `requester_id`, `resource_urn`, `columns`, `action`, `purpose`, `duration`, `status`, `approver_id`, `decision_reason`, `ticket_ref` | |
| `access_grant` | `id`, `tenant_id`, `principal_type`, `principal_id`, `resource_urn`, `columns`, `action`, `purpose`, `granted_by`, `request_id`, `expires_at`, `revoked_at` | Materialized into OPA + Lakekeeper |
| `decision_log` | `id`, `tenant_id`, `principal_id`, `action`, `resource_urn`, `allow`, `policy_id`, `obligations` (jsonb), `at` | Sampled (100% for RESTRICTED) |
| `legal_hold` | `asset_id`, `reason`, `set_by`, `expires_at` | Blocks retention/erasure |

### `configure`

| Table | Key columns | Notes |
|---|---|---|
| `config_object` | `id`, `tenant_id`, `kind`, `name`, `current_revision`, `labels` (jsonb), `status` (jsonb) | K8s-style `spec`/`status` split |
| `config_revision` | `object_id`, `revision`, `spec` (jsonb), `spec_hash`, `author`, `message`, `validation` (jsonb), `approved_by`, `created_at` | Immutable |
| `config_application` | `object_id`, `revision`, `environment`, `applied_at`, `applied_by`, `result` | |
| `drift_report` | `id`, `tenant_id`, `kind`, `name`, `git_hash`, `live_hash`, `detected_at`, `status` | |
| `feature_flag` | `key`, `tenant_id`, `enabled`, `rollout_percent`, `updated_by` | |

### `audit`

| Table | Key columns | Notes |
|---|---|---|
| `audit_event` | `id`, `tenant_id`, `seq`, `actor_type`, `actor_id`, `action`, `resource_type`, `resource_id`, `outcome`, `context` (jsonb), `prev_hash`, `hash`, `at` | Append-only; `hash = sha256(prev_hash + canonical(event))` |
| `audit_export` | `id`, `from_seq`, `to_seq`, `s3_uri`, `merkle_root`, `exported_at` | Daily |

### `assist`

| Table | Key columns | Notes |
|---|---|---|
| `conversation` | `id`, `tenant_id`, `user_id`, `title`, `created_at` | |
| `message` | `id`, `conversation_id`, `role`, `content_uri`, `citations` (jsonb), `tokens_in`, `tokens_out`, `model`, `at` | Content in S3 for large payloads |
| `prompt_template` | `id`, `tenant_id`, `name`, `version`, `template`, `status` | Versioned |
| `eval_run` | `id`, `suite`, `model`, `score`, `details_uri`, `at` | CI + nightly |

### `usage`

| Table | Key columns | Notes |
|---|---|---|
| `usage_event` | `id`, `tenant_id`, `project_id`, `kind` (`compute`,`storage`,`query`,`tokens`), `quantity`, `unit`, `resource_id`, `at` | Partitioned by day |
| `budget` | `tenant_id`, `period`, `amount`, `currency`, `alert_thresholds` | |

---

## 2. State machines (authoritative)

### `ingestion_run`

```text
QUEUED → RUNNING → VALIDATING → COMMITTING → SUCCEEDED
                 ↘ FAILED_QUALITY
                 ↘ FAILED_SOURCE (retryable)
                 ↘ FAILED_SYSTEM (retryable)
QUEUED/RUNNING → CANCELLED
```

### `job_run`

```text
QUEUED → ADMITTED → SCHEDULED → RUNNING → SUCCEEDED
                                       ↘ FAILED → (retry) QUEUED
                                       ↘ TIMED_OUT → (retry) QUEUED
                                       ↘ CANCELLED
QUEUED → CANCELLED
```

### `access_request`

```text
DRAFT → SUBMITTED → IN_REVIEW → APPROVED → PROVISIONED → EXPIRED
                             ↘ DENIED
APPROVED/PROVISIONED → REVOKED
```

### `config_revision`

```text
DRAFT → VALIDATED → APPROVED → APPLIED → SUPERSEDED
                 ↘ REJECTED
APPLIED → ROLLED_BACK
```

### `asset.lifecycle_state`

```text
draft → active → deprecated → archived
```

---

## 3. Invariants

1. `tenant_id` is immutable on every row; moving an asset between tenants is a copy + deprecate.
2. `urn` never changes; renames update `name` and emit `asset.renamed`.
3. A `pipeline_version` or `ingestion_revision` is immutable once a run references it.
4. `job_run.idempotency_key` is unique; retries mutate only `attempt`, never create a second `job_run` for the
   same key.
5. Terminal run states are immutable; `rerun_of` links new runs to old ones.
6. A dataset cannot move to `active` without an owner, a contract and a classification.
7. A `RESTRICTED` grant must have `expires_at` within 7 days unless it is role-based.
8. `access_grant` deletion is soft (`revoked_at`); the audit history is never deleted.
9. `lineage_edge` writes are idempotent on the natural key and monotonic in `observed_at`.
10. `config_revision.spec_hash` equals the hash of the canonical JSON spec; mismatch = corruption alert.

---

## 4. Data retention (operational DB)

| Table group | Retention | Mechanism |
|---|---|---|
| Runs/attempts/task runs | 24 months hot, then S3 archive | Monthly partition drop after export |
| Run events | 12 months | Partition drop |
| Decision log | 13 months (7 years for RESTRICTED, exported) | Export then drop |
| Audit | 7 years | Append-only, export to S3 with Object Lock |
| Discovery snapshots | 90 days | S3 lifecycle + row delete |
| Usage events | 36 months | Roll up to monthly |
| Conversations | 12 months (configurable) | Delete cascade |

---

## 5. Sizing and partitioning notes

- `job_run`, `task_run`, `run_event`, `usage_event`, `decision_log` are **monthly partitioned** (pg_partman or
  native declarative partitioning) — the only tables that grow unbounded.
- Indexes: `(tenant_id, status, created_at desc)` on runs; `(asset_id, version)` on schema versions;
  `(from_urn)` and `(to_urn)` on lineage; GIN on `spec jsonb` only where UI filters require it.
- Target: keep the largest table under 500M rows per 24 months; archive beyond that.
- Read replicas serve catalog search and UI list endpoints; writes go to primary.
