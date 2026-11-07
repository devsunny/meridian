# ADR-0004: OpenMetadata as the metadata backbone

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Data Governance, Platform Engineering, Chief Data Officer

## Context

"Mature metadata management" means: a searchable catalog, schemas and versions, ownership, a business
glossary, tags/classifications, lineage (table and column), data quality results, and a UI that stewards will
actually use. Building all of that is a multi-year product effort.

Candidates: OpenMetadata, DataHub, Collibra/Alation (commercial), Apache Atlas (legacy), build on Postgres +
OpenSearch.

## Decision

Adopt **OpenMetadata** as the metadata backbone for business metadata (glossary, descriptions, ownership,
tags) and as the lineage/discovery surface.

- The platform's `catalog` service remains the **system of record for technical and operational metadata**:
  datasets, schema versions, contracts, quality results, run↔dataset links, lineage edges (hot copy).
- Writes flow **one way**: platform → OpenMetadata via API/events. Stewards may edit descriptions/glossary in
  OpenMetadata; those fields are read back and cached by the platform (never edited in two places).
- A `CatalogPort` abstraction isolates OpenMetadata; a nightly full-diff reconciliation job detects drift.
- The platform UI embeds catalog search and asset summaries via API and deep-links to OpenMetadata for
  glossary and full lineage exploration.

## Rationale

| Criterion | OpenMetadata | DataHub | Build |
|---|---|---|---|
| Time to value | Weeks | Months (Kafka, Neo4j, ES) | Years |
| Governance UX | Strong (glossary, tests, roles) | Strong, more engineering-centric | Whatever we build |
| Lineage | Table + column | Best-in-class, column-level | Hard |
| Ops footprint | Postgres + OpenSearch | Kafka + Neo4j + ES + GMS | Low |
| Extensibility | Ingestion framework, APIs | Very high (events, actions) | Total |
| Fit with our stack | Reuses our Postgres/OpenSearch | Extra infra | — |

OpenMetadata gives 80% of the governance value at 20% of the operational cost, and it reuses the Postgres and
OpenSearch we already run. DataHub is the better choice if lineage at massive scale and event-driven
extensibility dominate; that is a credible future migration because all writes go through `CatalogPort`.

## Consequences

**Positive**
- Stewards get a mature UI on day one; no "catalog v0" that nobody trusts.
- Glossary, classifications and data-quality results are first-class.
- Lower operational burden than DataHub.

**Negative / accepted**
- Two UIs (platform + OpenMetadata) is a real UX risk; mitigated by embedding, deep links and a clear "where do
  I do what" guide.
- Dual metadata stores require reconciliation and a documented ownership rule per field.
- OpenMetadata upgrades can lag our API needs; the port abstraction caps the blast radius.
- If we later migrate to DataHub, we must re-implement the port adapter and migrate glossary/lineage.

## Alternatives considered

1. **DataHub.** More powerful lineage and event model, but Kafka + Neo4j + Elasticsearch is a heavy footprint
   for phase 1 and duplicates infrastructure we already operate.
2. **Build a catalog.** Rejected: glossary UX, lineage ingestion and search relevance are years of work that is
   not our differentiator.
3. **Collibra/Alation.** Strongest governance, but cost and integration effort are disproportionate for
   phase 1–2; revisit at enterprise-wide deployment.

## Compliance

Field-level ownership is documented in doc 04 §4.1. Revisit at phase 3 if column-level lineage coverage is
below 80% or if OpenMetadata cannot meet a required compliance control.
