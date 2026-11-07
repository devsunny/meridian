# ADR-0002: Apache Iceberg on S3 with a Lakekeeper REST catalog

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Data Architecture, Platform Engineering, FinOps

## Context

The lakehouse must serve Spark (batch), Trino (interactive/federation), dbt (transforms), and future engines
(Flink, DuckDB, Snowflake external tables). It needs ACID commits, schema evolution, time travel for
reproducibility, row-level deletes for GDPR erasure and CDC merges, and multi-tenant access control at the
namespace/table level.

Candidates: Iceberg, Delta Lake, Apache Hudi. Catalog candidates: AWS Glue, Lakekeeper, Nessie, Unity, Hive
Metastore.

## Decision

- **Table format:** Apache Iceberg v2, one warehouse per environment, tables under `s3://edp-lake-{env}`.
- **Catalog:** **Lakekeeper** (Iceberg REST catalog) as the primary catalog, deployed in `edp-data`, backed by
  Postgres, with per-tenant namespaces and RBAC.
- **No Glue as primary catalog.** Glue may be added later as a *mirror* only if an AWS-native engine requires
  it; it is not the source of truth.
- **Partitioning and file standards** are enforced by the platform (doc 02 §2.1), not left to pipeline authors.

## Rationale

| Criterion | Iceberg + Lakekeeper | Glue + Iceberg | Delta | Hudi |
|---|---|---|---|---|
| Engine neutrality | Excellent (REST spec) | Good (AWS-centric) | Databricks gravity | Spark-centric |
| Multi-tenant RBAC | Built-in namespaces/roles | Thin (IAM/Lake Formation) | Via vendor | Limited |
| Row-level deletes | v2 merge-on-read | Yes | Yes | Yes |
| Operational cost | One service + Postgres | Serverless | Vendor | One service |
| Portability off AWS | Yes | No | Partial | Partial |
| Ecosystem momentum | Very high | High | High | Medium |

Lakekeeper gives us the authorization surface we need for a multi-tenant lakehouse without making every
engine's access control a bespoke integration. It is a stateless service backed by Postgres, so its HA story
is the same as the rest of the control plane.

## Consequences

**Positive**
- Any Iceberg-compatible engine can read the same tables.
- Namespace-level grants map cleanly to tenant/project boundaries.
- Catalog metadata is portable (Postgres dump + S3), which simplifies DR and exit.

**Negative / accepted**
- Athena/EMR integration is less turnkey than Glue; Trino is the primary SQL path.
- We operate one more stateful service and must back up its Postgres schema.
- Lakekeeper's permission model must be reconciled with `govern` (hourly job + event-driven invalidation).

## Alternatives considered

1. **Glue only.** Simplest on AWS, but weak multi-tenant RBAC and hard lock-in. Would force Lake Formation
   (complex, per-table grants, poor cross-account ergonomics) for governance.
2. **Nessie.** Excellent branching/tagging for CI-style data dev, but a smaller community and another
   git-semantics learning curve; Lakekeeper's RBAC is a better fit for the primary need.
3. **Delta Lake.** Strong product, but the ecosystem gravity pulls toward one vendor; row-level deletes and
   REST catalog maturity were weaker at decision time.

## Compliance

Revisit if Lakekeeper does not reach production-grade HA within phase 1, or if a required engine cannot speak
Iceberg REST. Fallback: Glue as catalog + Lake Formation grants, with an adapter in `catalog`.
