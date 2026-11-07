# ADR-0005: OPA and ABAC, enforced at the point of data access

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Security Architecture, Data Governance, Platform Engineering

## Context

Authorization must answer questions that pure RBAC cannot: *may this analyst read `ssn` in `finance.invoices`
for the "fraud investigation" purpose, from the corporate network, for the next 7 days, without exporting
rows?* The answer must be consistent across the API, SQL queries, object storage, search and vector retrieval,
and it must be explainable to auditors.

Candidates: RBAC only, OPA (Rego), AWS Verified Permissions / Cedar, embedded per-service checks, Ranger.

## Decision

- **RBAC for coarse grants** (roles → resource patterns) and **ABAC for conditions** (classification, purpose,
  time, tenant, network zone, request TTL).
- **OPA** is the single policy decision point. Services call `govern /decide` (a thin, cached wrapper over
  OPA) rather than evaluating policy locally.
- Policies are **Rego in Git**, tested in CI, signed and shipped as bundles. A policy change is a pull request
  with security approval — never a UI toggle.
- Enforcement happens at **every data-access point**: service APIs, Trino (table/column/row/mask), Lakekeeper,
  S3 session policies, OpenSearch/vector pre-filtering.
- Decisions carry **obligations**, not just allow/deny: row filters, column masks, row caps, watermarks.
- Every decision is logged with policy id, inputs hash and obligations for audit and "explain access".

## Rationale

- OPA is domain-agnostic, testable (`opa test`), widely deployed, and has no per-request cost.
- Centralizing the PDP avoids policy drift across nine services — the classic failure of embedded checks.
- ABAC is what makes `RESTRICTED` data usable rather than banned: access is granted by context, not by
  permanently widening a role.
- Cedar/AVP is attractive on AWS but couples policy to one cloud and has a smaller ecosystem of tooling for
  our non-AWS enforcement points (Trino, Lakekeeper).

## Consequences

**Positive**
- One policy language, one test suite, one audit trail of decisions.
- Time-bound, purpose-bound access without role explosion.
- Auditors can read the policy and the tests, not just a screenshot.

**Negative / accepted**
- Every request pays a policy evaluation (mitigated by 30 s decision cache, invalidated on `policy.changed`).
- OPA and Rego are another system to operate and another skill to hire.
- `govern` becomes a critical-path dependency; it must be highly available and fail **closed** for
  `RESTRICTED` data (cached decisions with short TTL, degraded mode denies writes).
- Keeping Lakekeeper grants and OPA policy in sync requires a reconciler and drift alerts.

## Alternatives considered

1. **RBAC only.** Simple, but cannot express purpose/time/classification; would force either over-granting or
   permanent denial of regulated data.
2. **AWS Verified Permissions (Cedar).** Strong product and formally verifiable, but AWS-only and awkward for
   Trino/Lakekeeper/OpenSearch enforcement; keep as a future option for an AWS-only deployment.
3. **Per-service checks.** Rejected: policy drift, inconsistent audit, impossible to prove compliance.
4. **Apache Ranger.** Mature in Hadoop estates, but plugin coverage for our stack is uneven and the policy
   model is less expressive than Rego.

## Compliance

Policy suite must maintain 100% branch coverage of roles × classifications × actions. Revisit if `govern`
becomes a latency bottleneck (p99 > 25 ms) or if Cedar gains first-class Trino/Lakekeeper integration.
