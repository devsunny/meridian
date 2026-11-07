# ADR-0001: Compose proven engines; own the control plane and the glue

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Chief Architect, Head of Data Platform, Security Architect

## Context

The platform must support ingestion from a dozen source families, batch processing, scheduling, durable async
execution, catalog/lineage, fine-grained authorization, and AI retrieval. Every one of those capabilities has
at least two mature open-source or managed implementations. Building any of them from scratch would consume
the entire roadmap before a single business user is served.

At the same time, none of the off-the-shelf products provides the combination we need: multi-tenant isolation,
source-ACL propagation, a business-user ingestion experience, policy-enforced access at the data layer, and a
single audit trail across engines.

## Decision

We **compose** established engines for execution, query, orchestration, catalog and policy, and we **build**
the control plane that binds them:

- Engines: Spark, dbt, Trino, Temporal, Argo Workflows, OpenMetadata, OPA, Lakekeeper, OpenSearch.
- We build: tenancy, the configuration/definition model, the connector SDK and runtime, the ingestion and
  pipeline UX, the governance layer, the execution bridge, audit, and AI enablement.

Integration is done through standards (Iceberg REST, OpenLineage, CloudEvents, OpenTelemetry, OIDC), not
through engine-specific plugins where avoidable. Each engine sits behind a port interface so it can be
replaced without changing domain logic.

## Consequences

**Positive**
- Time to first useful release measured in weeks, not quarters.
- Access to talent and community documentation for every engine.
- Each engine is independently upgradable and replaceable.

**Negative / accepted**
- We inherit the operational burden of running 8+ stateful systems.
- Version upgrades can break integrations; we need contract tests against engine versions.
- "Glue" is real product surface: the control plane is not a thin script layer and must be staffed as such.
- Two systems of record for metadata (platform + OpenMetadata) require reconciliation (see ADR-0004).

## Alternatives considered

1. **Build an end-to-end platform** (own scheduler, own catalog, own query layer). Rejected: 3–4 years to
   parity, and we would still be worse at query optimization and lineage than the incumbents.
2. **Buy a full suite** (Databricks/Snowflake + Collibra + Fivetran). Rejected: excellent engines, but
   per-seat/per-row economics at 2 PB and weak fit for on-prem sources, custom connectors and our governance
   model. Also creates a single-vendor dependency the board explicitly wants to avoid.
3. **Thin portal over one vendor.** Rejected: no differentiation, and the business-user UX requirement cannot
   be met by a vendor's admin console.

## Compliance

Revisit if: (a) any engine's license changes, (b) two engines merge into one viable suite, or (c) operating
cost of the composed stack exceeds 25% of total platform cost for two consecutive quarters.
