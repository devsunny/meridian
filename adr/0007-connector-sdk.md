# ADR-0007: First-party connector SDK and sandboxed runtime

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Connect Engineering, Security, Data Governance

## Context

We need connectors for SFTP, HTTPS REST, MCP, file systems, SharePoint, OneDrive, Google Drive, Box, S3, JDBC,
Kafka and webhooks — plus a long tail. Each source has its own auth model, pagination, delta semantics and ACL
structure. Connectors run inside customer networks for some sources, and handle credentials for all of them.

Buying a connector platform (Fivetran, Airbyte Cloud) gives breadth but not source-ACL propagation, tenant-scoped
secrets, on-prem agent relay, MCP, or our audit/lineage semantics. Pure OSS Airbyte gives images but its control
plane assumes its own orchestrator and metadata model.

## Decision

Build a **first-party connector SDK** (Python) and a **sandboxed runtime** (one connector task per pod), and
offer an **Airbyte adapter** for long-tail sources.

- SDK defines a small contract: `test`, `discover`, `describe`, `read`, `acl`, `classify`.
- The runtime — not the connector — handles checksums, manifests, quarantine, bronze commit, checkpoints,
  retries, OTel spans and secret mounting.
- Connectors ship as signed OCI images with declared egress allowlists and resource profiles.
- On-prem sources are reached through an outbound-only `remote-agent`.
- Airbyte sources run as adapter-wrapped images; they are marked `third_party` in the catalog and do not
  propagate source ACLs (access is governed at the dataset level instead).

## Rationale

- Governance requirements (ACLs, PII hints, lineage, tenant secrets) are cross-cutting and must be enforced by
  the runtime, not re-implemented per connector.
- A tiny contract means a new connector is ~300–800 lines plus fixtures — days, not months.
- Sandboxing per task limits blast radius of a malicious or buggy connector and makes spot eviction safe.
- The Airbyte adapter prevents "connector envy" from derailing the roadmap while keeping the governance model
  intact for first-party sources.

## Consequences

**Positive**
- Full control over auth, secret handling, ACL mapping and audit.
- Connector developers only think about one source, not platform plumbing.
- Uniform behavior: every connector is resumable, traced and quarantined the same way.

**Negative / accepted**
- We own the maintenance of 12+ connector families (API drift, auth changes, rate limits) — a permanent team.
- The Airbyte adapter is a second-class citizen: no source ACLs, different error semantics, image supply-chain
  risk. It must be flagged in the UI and catalog.
- Per-task pods have cold-start and networking overhead; scale-to-zero is only viable with prefetching.
- Building an MCP connector requires careful output-size and prompt-injection controls (doc 06 §6.3).

## Alternatives considered

1. **Airbyte as the control plane.** Fast breadth, but governance, tenancy and scheduling would live in a second
   platform; source ACLs and MCP unsupported.
2. **Fivetran/similar managed.** Excellent reliability, but per-row pricing and no on-prem agent for file shares
   or custom MCP; data residency constraints.
3. **One monolithic "integration service".** Rejected: no isolation, no independent scaling, one bad connector
   takes down ingestion.
4. **No SDK — write bespoke jobs per source.** Rejected: inconsistent governance and unmaintainable.

## Compliance

All connector images must pass the sandbox test (egress allowlist, non-root, read-only FS) before catalog
publication. Quarterly review of connector freshness and API-deprecation notices.
