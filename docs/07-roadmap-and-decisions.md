# 7. Delivery Roadmap, Build vs Buy and Risks

> Covers "how do we get there from here". The design above is ~18 months of work for a team of 12–16; this
> document sequences it so that something useful ships in week 6, not month 9.

---

## 7.1 Sequencing principles

1. **Vertical slice first.** One source type (S3 + REST) → one dataset → one dashboard → one power user. Prove
   the whole path before broadening the connector catalog.
2. **Governance early, not later.** Retrofitting RBAC, lineage and audit into a working system costs 3× more
   than building the hooks first. Classification can mature later; the hooks cannot.
3. **Buy the commodity, build the differentiator.** The differentiator is the business-user experience and the
   governance model — not another Spark scheduler.
4. **No phase ships without an SLO and a runbook.** "Production-ready" is a gate, not a label.
5. **Platform team dogfoods from week 1.** Every internal dataset goes through the platform; if it hurts us, it
   will hurt users.

---

## 7.2 Phases

### Phase 0 — Foundations (weeks 0–6)

**Theme:** a thin vertical slice that a real user can complete.

| Deliverable | Detail |
|---|---|
| AWS landing zone | Terraform: VPC, EKS, RDS, S3, KMS, OpenSearch, IRSA, secrets |
| GitOps | Argo CD, Helm chart template, dev/staging/prod, promotion flow |
| Control plane skeleton | `iam`, `connect`, `ingest`, `orchestrate`, `catalog`, `configure`, `audit` with health, auth, tenancy, outbox |
| Identity | OIDC with Entra ID, tenant/project model, 6 built-in roles |
| Storage | S3 zones, Iceberg + Lakekeeper, Trino, 2 datasets end-to-end |
| Connectors | S3, HTTPS REST (OpenAPI-driven), manual upload (CSV/JSON/Parquet) |
| Execution | Temporal, Argo, one Spark job template, local executor for dev |
| Catalog | Dataset registration, schema versioning, OpenLineage capture from connectors, OpenMetadata deploy |
| UI | Login, catalog list, ingestion wizard (source → preview → map → schedule), run detail |
| Ops | Prometheus/Grafana/Loki/Tempo, 3 dashboards, 2 alerts, backup/restore tested |

**Exit criteria:** a pilot user ingests a REST API into bronze, transforms to gold with dbt, sees lineage in
the catalog, and queries it from Trino. SLO dashboards exist. No manual `kubectl` in the path.

### Phase 1 — Self-service breadth (weeks 6–16)

**Theme:** the connector catalog and the governance people actually feel.

| Deliverable | Detail |
|---|---|
| Connectors | SFTP, SharePoint, OneDrive, Google Drive, Box, file system via `remote-agent` |
| Ingestion features | Incremental watermarks, delta tokens, quarantine, retries, backfill, scheduling UI |
| Pipeline features | Spark + dbt + SQL + Python types, DAG editor (form-based), dependencies, SLAs |
| Governance | OPA, ABAC policies, access requests + approvals, column masks in Trino, audit export to SIEM |
| Catalog | Lineage from Spark/dbt/Trino, quality results, glossary seed, search |
| Config | Revisioned config, Git export, drift detection, promotion |
| Autoscaling | KEDA, Karpenter spot pool, Kueue quotas for 3 classes |
| Ops | 10 runbooks, game day #1, DR drill #1, cost showback v1 |

**Exit criteria:** 5 tenants, 40 connections, 80% of new sources onboarded without platform-team help. Access
requests fully self-service. p95 run start < 10 s.

### Phase 2 — Unstructured + AI + scale (weeks 16–28)

**Theme:** documents, RAG, MCP, and the operational maturity to run 10× the load.

| Deliverable | Detail |
|---|---|
| Unstructured pipeline | Extract, OCR, PII, chunk, embed, index, ACL propagation, re-ACL job |
| RAG | `assist` service, ACL-aware retrieval, citations, evaluation harness |
| MCP | Server (8 tools) + client connector, OAuth 2.1, audit |
| Semantic layer | dbt metrics, certified datasets, BI integration guide, "ask your data" beta |
| Autoscaling v2 | Fair sharing across tenants, preemption policies, Trino resource groups, Spark AQE tuning |
| Resilience | Multi-AZ failover tested, DR drill #2, chaos suite in CI |
| Governance v2 | Classification automation (Macie/Comprehend), retention jobs, DSAR/erasure workflow |
| Scale | Load test 2× baseline; 1,000 concurrent runs; 2,000 pods |

**Exit criteria:** RAG answers with zero unauthorized retrievals in the eval suite; 60% batch CPU on spot;
MTTR < 30 min; SOC 2 evidence collection automated.

### Phase 3 — Differentiation (weeks 28–40)

**Theme:** the platform becomes a data product ecosystem rather than a pipeline tool.

| Deliverable | Detail |
|---|---|
| Data products | Product templates, SLAs, publish/subscribe, consumer contracts, "used by" tracking |
| Marketplace | Internal catalog storefront with certification, preview, request-access-in-one-click |
| Copilot v2 | Draft pipelines from NL, suggested fixes, steward assistant, auto-documentation |
| Streaming | MSK + Debezium CDC + Flink micro-batch to Iceberg; streaming datasets in catalog |
| Cost intelligence | Per-pipeline cost, right-sizing recommendations, budget enforcement |
| Extensibility | Public connector SDK, plugin marketplace, webhook framework, Terraform provider |
| Multi-region | Active-passive DR in second region, residency routing |

**Exit criteria:** ≥ 70% of datasets consumed by 2+ workloads; ≥ 30% cost reduction vs phase-0 baseline per TB;
external teams building connectors without platform-team involvement.

---

## 7.3 Team topology

| Squad | Size | Owns |
|---|---|---|
| **Platform core** | 5–6 | `iam`, `configure`, `orchestrate`, scheduler, execution bridge, API gateway, tenancy |
| **Connectivity** | 3–4 | `connect`, connector SDK, connector catalog, `remote-agent`, source ACLs |
| **Data & metadata** | 3–4 | lakehouse, `catalog`, lineage, quality, Trino, OpenMetadata integration |
| **Governance & security** | 2–3 | `govern`, OPA, classification, audit, access workflows, compliance evidence |
| **Experience** | 3–4 | web app, wizard, catalog UX, design system, accessibility |
| **SRE / platform ops** | 2–3 | EKS, Karpenter/Kueue/KEDA, observability, cost, on-call, DR |
| **AI** | 2 | `assist`, RAG, MCP, semantic layer, evaluations |
| **Product/design** | 1–2 | roadmap, user research, pilot management |

Total ~20 at full strength, ~12 to reach phase 1 exit. **On-call:** one rotation across platform+SRE, follow-the-sun
not required for a single-region deployment; 24/7 for tier-0 only.

**RACI (abridged):**

| Decision | Accountable | Consulted |
|---|---|---|
| New connector in catalog | Connectivity lead | Security, Data governance |
| Policy model change | Governance lead | Security, Legal |
| Dataset certification | Data steward | Domain owner |
| Production promotion | SRE on-call | Service owner |
| New tenant onboarding | Platform core | Finance (chargeback), Security |
| Model/provider approval | AI lead | Security, Legal, Procurement |

---

## 7.4 Build vs buy

| Capability | Decision | Rationale | If we bought |
|---|---|---|---|
| Ingestion control plane | **Build** (connectors on SDK) | Governance, ACLs, MCP, agent relay are the differentiator | Fivetran/Airbyte: fast start, weak ABAC/lineage, per-row pricing at scale |
| Execution engines | **Buy/OSS** (Spark, Trino, dbt) | Commodity, mature, huge talent pool | Databricks/Snowflake: excellent, but lock-in and cost at 2 PB |
| Orchestration | **OSS** (Temporal + Argo) | Durable state is hard; both are proven | Airflow managed: simpler ops, weaker async semantics; Step Functions: lock-in |
| Catalog | **OSS + integrate** (OpenMetadata) | Glossary/lineage/UI are years of work | Collibra/Alation: strong governance, expensive, heavy integration; DataHub: viable alternative |
| Policy | **OSS** (OPA) | Testable, portable, well understood | AVP/Cedar: AWS-native, less portable |
| Query | **OSS** (Trino) | Federation + policy plugin + no per-query cost | Athena: serverless, less control; Snowflake: cost |
| BI | **Buy** (Power BI/Tableau) | Not our product | — |
| LLM | **Buy/route** (Bedrock/Azure OpenAI) | Model landscape moves too fast to own | — |
| Vector DB | **Reuse OpenSearch** | One fewer system to operate | Pinecone: better recall ops, another vendor |
| Secret store | **Buy** (Secrets Manager) | Rotation + audit for free | Vault: portable, more ops |
| Observability | **OSS + managed** (Grafana Cloud optional) | OTel keeps options open | Datadog: great DX, costly at volume |
| Identity | **Buy** (Entra ID/Okta) | Never build IdP | — |

**Rule of thumb:** build where governance, tenancy or UX differentiates; buy where the market has a mature,
standards-based product and our value is integration, not implementation.

---

## 7.5 Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Connector long tail consumes the roadmap | High | High | 12 families + Airbyte adapter + public SDK; say no to one-off connectors |
| R2 | Two orchestrators create split-brain state | Medium | High | Enforce the ownership rules (§3.1) in code review; run-state reconciliation job |
| R3 | Metadata dual-write drift (platform ↔ OpenMetadata) | High | Medium | Outbox + idempotent consumer + nightly full-diff reconciliation alerts |
| R4 | Per-user OAuth token expiry/revocation breaks pipelines | High | Medium | Token broker, proactive refresh, expiry alerts 7 days ahead, service-account fallback |
| R5 | Noisy neighbour starves tier-1 pipelines | Medium | High | Kueue quotas + priorities + preemption; per-tenant rate limits; load tests |
| R6 | Unstructured PII leaks into vectors or prompts | Medium | Critical | Redact before embed, classification gate, ACL pre-filter, eval suite with 0-leak gate |
| R7 | Cost overrun (S3 + compute + observability) | High | Medium | Showback, budgets, spot, lifecycle, cardinality limits, monthly cost review |
| R8 | Policy complexity becomes unauditable | Medium | High | Fixed role set, policy tests, decision logs, quarterly access reviews, "explain access" UI |
| R9 | K8s operational burden exceeds team capacity | Medium | High | Managed EKS, Karpenter, minimal add-ons, no self-managed control plane, SRE ratio target |
| R10 | Business users still need engineering help | High | High | Wizard usability testing every sprint, templates, "no-code first" rule for new features |
| R11 | Vendor lock-in (Iceberg catalog, metadata) | Low | Medium | Standards (Iceberg REST, OpenLineage, CloudEvents), ports/adapters, export tooling |
| R12 | Compliance evidence gaps at audit time | Medium | High | Continuous control monitoring from day 1; audit events are a product requirement |

---

## 7.6 Open decisions (need stakeholder input)

These are the choices this design cannot make for you. Recommended defaults are in brackets.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Primary query/warehouse strategy | (a) Trino only (b) Trino + Snowflake (c) Databricks | **(a)** for phase 0–2; add (b) only if finance/BI already standardized on it |
| D2 | Metadata backbone | OpenMetadata vs DataHub vs build | **OpenMetadata**, with a `CatalogPort` abstraction |
| D3 | Tenancy model | Business unit vs external customers vs both | **Business unit first**; design isolation tiers now, sell externally later |
| D4 | Build team location/size | 12 vs 20 vs 30 engineers | **12 to phase 1**, scale to 20 for phase 2–3 |
| D5 | Cloud scope | AWS only vs multi-cloud | **AWS only** for 18 months; portability via K8s/S3/Iceberg, not premature multi-cloud |
| D6 | LLM provider | Bedrock vs Azure OpenAI vs on-prem | **Bedrock default + gateway abstraction**; per-tenant override |
| D7 | Data residency | Single region vs EU/US split | **Region-pinned tenants** from phase 1; full multi-region in phase 3 |
| D8 | Chargeback vs showback | Showback vs hard chargeback | **Showback** first; chargeback after 2 quarters of trustworthy metering |
| D9 | Airbyte adoption | None vs adapter vs control plane | **Adapter only** (phase 2) |
| D10 | Build vs buy for the UI | Custom Next.js vs embedded BI/portal | **Custom** — the UX is the differentiator |

---

## 7.7 Success metrics

| Category | Metric | Phase 1 target | Phase 3 target |
|---|---|---|---|
| Adoption | Weekly active users / licensed | 40% | 70% |
| Self-service | Sources onboarded without platform team | 60% | 85% |
| Coverage | Datasets with owner + contract + lineage | 70% | 98% |
| Reliability | Pipeline success rate (excl. data errors) | 97% | 99.5% |
| Freshness | Datasets meeting SLA | 90% | 99% |
| Governance | Access requests resolved < 1 day | 70% | 95% |
| Governance | Unauthorized access findings | 0 | 0 |
| Performance | p95 run start | < 15 s | < 10 s |
| Cost | Batch CPU on spot | 40% | 65% |
| Cost | Cost per TB processed (indexed) | baseline | −40% |
| Experience | Ingestion wizard completion rate | 70% | 90% |
| AI | RAG groundedness / policy compliance | n/a | > 90% / 100% |

---

## 7.8 First 30 days (concrete)

| Week | Outcome |
|---|---|
| 1 | Stakeholder interviews (8 users, 3 stewards, security, finance); confirm D1–D3; pick pilot domain |
| 2 | Landing zone plan + cost envelope; repo bootstrap; ADRs 0001–0003 accepted |
| 3 | EKS + GitOps + Postgres + S3/Iceberg/Trino running in dev; `iam` + gateway skeleton |
| 4 | S3 connector end-to-end into bronze; catalog registration; first lineage edge; wizard v0 in front of 2 pilot users |
| 5 | REST connector; scheduling via Temporal; run detail page; first dashboard on gold |
| 6 | Pilot user ingests a real source unaided; retro; phase-1 plan re-baselined |
