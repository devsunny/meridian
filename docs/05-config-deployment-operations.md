# 5. Configuration Management, Deployment and Operations

> Covers FR-11, FR-15, NFR-01/03/08/10/11. Answers: how does this thing get configured, deployed, observed,
> recovered — and how do we keep 400 connectors and 15k daily runs from becoming unoperable?

---

## 5.1 Two kinds of configuration (do not mix them)

| Kind | Examples | System of record | Change path |
|---|---|---|---|
| **Infrastructure configuration** | VPCs, node pools, IAM, RDS, Helm values, cluster add-ons | Git + Terraform/Helm | PR → plan → approval → Argo CD/Terraform apply |
| **Platform configuration** | tenants, connections, ingestion definitions, pipelines, schedules, policies, quotas | `configure` service (Postgres), exported to Git | API/UI → revision → validation → approval (if gated) → apply |

Infrastructure never lives in the platform DB; platform config never requires a cluster change. The bridge is
**export**: every platform object can be rendered to YAML in the GitOps repo, and a nightly drift job compares
Git ↔ live, reporting (not auto-correcting) differences.

### Configuration service

```http
GET    /v1/config/{kind}/{name}
GET    /v1/config/{kind}/{name}/revisions?limit=20
POST   /v1/config/{kind}/{name}          # create draft
PUT    /v1/config/{kind}/{name}          # new revision (optimistic concurrency via resourceVersion)
POST   /v1/config/{kind}/{name}:validate
POST   /v1/config/{kind}/{name}:apply    # materialize; may require approval
POST   /v1/config/{kind}/{name}:rollback {toRevision: 7}
POST   /v1/config/{kind}/{name}:promote  {from: staging, to: production}
GET    /v1/config/drift?tenant=acme
```

Rules:

- **Immutable revisions.** Every save creates a revision with author, diff, timestamp and validation result.
- **Schema-validated.** JSON Schema per kind, versioned (`v1`, `v1beta1`); conversion webhooks for upgrades.
- **Effective-dated.** `spec.effectiveFrom` allows pre-staging a change (e.g., new schedule from Jan 1).
- **Approval gates.** Policy decides which kinds/tenants require approval (prod + `RESTRICTED` by default).
- **Referential integrity.** Deleting a connection used by an ingestion is blocked; deleting a dataset used by
  a pipeline creates a deprecation task instead.
- **Secrets by reference.** `credentialRef: arn:aws:secretsmanager:...` is validated for existence and
  readability at apply time, never resolved into the config.

### Example: versioned ingestion definition

```yaml
apiVersion: ingest.edp.example/v1
kind: Ingestion
metadata:
  name: acme-box-invoices
  tenant: acme
  labels: { domain: finance, criticality: tier1, cost_center: FIN-42 }
spec:
  source:
    connectionRef: box-finance
    resource: /Invoices/2026
    include: ["**/*.pdf", "**/*.csv"]
  target:
    dataset: acme.finance.bronze_invoices
    mode: append
    partitionBy: [days(ingest_ts)]
  changeDetection: { strategy: modified_since, column: modified_at, overlap: 15m }
  schedule: { cron: "0 2 * * *", timezone: America/New_York, catchup: one }
  quality: { contract: acme.finance.bronze_invoices, onFailure: quarantine }
  limits: { maxConcurrentFiles: 8, maxRuntime: 4h, maxBytes: 50Gi }
  owner: finance-data@acme.example
status:
  observedGeneration: 12
  phase: Ready
  lastRun: { id: run_01J8Z9K3T7, status: SUCCEEDED, at: "2026-10-31T02:14:03Z" }
```

### GitOps repository layout

```text
platform-gitops/
├── apps/                          # Argo CD Applications (one per service, env overlay)
├── clusters/
│   ├── dev/       { kustomization.yaml, patches/ }
│   ├── staging/   { ... }
│   └── prod/      { ... }
├── charts/
│   ├── edp-service/               # generic chart: deployment, hpa, pdb, netpol, servicemonitor
│   ├── edp-connector/             # connector runtime + KEDA scaler
│   └── edp-trino/  edp-argo/  edp-temporal/
├── infra/
│   ├── modules/{vpc,eks,rds,s3,kms,opensearch,iam,observability}
│   └── envs/{dev,staging,prod}/{main.tf,backend.tf,terraform.tfvars}
├── config/
│   ├── tenants/{acme,globex}/...
│   └── policies/                  # Rego + tests + bundle manifest
└── ci/                            # shared pipeline templates
```

**Promotion:** build once → deploy to dev automatically → staging on merge to `main` → production on a signed
release tag + approval. Images are promoted by digest, never rebuilt per environment.

### Environments

| Env | Purpose | Data | Scale | Access |
|---|---|---|---|---|
| `local` | Development | Synthetic seed | Docker Compose | Developer laptop |
| `dev` | Integration, connector dev | Synthetic + masked sample | 10% of prod | Platform team |
| `staging` | Release validation, perf, DR drills | Masked production subset | 50% of prod | Platform + QA |
| `prod` | Production | Real | 100% | Break-glass + on-call |
| `prod-dr` | Warm standby | Replicated | Can run tier-0 at 50% | Break-glass |

---

## 5.2 CI/CD

### Service pipeline

```text
lint (ruff/eslint) → typecheck (mypy/tsc) → unit tests (≥70% on domain) → contract tests (OpenAPI diff)
→ build (multi-arch) → SBOM (syft) → scan (trivy, fails on HIGH) → sign (cosign) → push
→ helm values bump (digest) → PR to gitops → Argo CD sync → smoke tests → promote
```

### Connector pipeline

- Contract tests against recorded fixtures (VCR-style), never live SaaS in CI.
- Sandbox test: run connector image with a restricted NetworkPolicy, assert it only reaches allowed hosts.
- ACL fixture test: discovery must return expected principals for a sample hierarchy.
- Chaos test: kill the pod mid-read, assert checkpoint resume produces no duplicates.

### Infra pipeline

`terraform fmt/validate → plan (OIDC to AWS) → cost diff (infracost) → policy check (OPA/conftest) → approval
→ apply`. Drift detection runs hourly and opens a ticket on divergence.

### Policy pipeline

`opa fmt → opa test → conftest verify against golden manifests → bundle sign → publish → govern reload`. A
policy change that would widen access requires a security approval and is announced in the audit channel.

---

## 5.3 EKS reference architecture

| Concern | Decision |
|---|---|
| Cluster | EKS 1.30+, private API endpoint, audit logs to CloudWatch + S3 |
| Networking | VPC /16, 3 AZ, private node subnets, public ALB subnets, one NAT/AZ (3 for `isolated` tenants) |
| CNI | VPC CNI with prefix delegation; NetworkPolicy via Cilium or Calico (VPC CNI network policy is limited) |
| Ingress | AWS Load Balancer Controller → Envoy Gateway → services; WAF + Shield on ALB |
| DNS/TLS | ExternalDNS + cert-manager (ACME internal CA); mTLS via istio ambient (phase 2) |
| Identity | IRSA for all AWS access; EKS Pod Identity for newer clusters; no node instance roles with broad rights |
| Nodes | Bottlerocket; Karpenter; node pools as in §3.6 |
| Storage | EBS gp3 for Postgres/OpenSearch (managed), EFS only for shared scratch (rare), S3 for everything else |
| Add-ons | vpc-cni, coredns, kube-proxy, ebs-csi, efs-csi, metrics-server, snapshot-controller |
| Security | Kyverno (policy-as-code admission), Falco (runtime), Trivy operator, sealed secrets via ESO, PodSecurity `restricted` |
| Backup | Velero (cluster state) + RDS PITR + S3 versioning/replication |
| Cost | Kubecost/OpenCost + AWS CUR; tags `tenant`, `env`, `cost_center`, `pipeline` on every resource |

### Namespace plan

| Namespace | Contents | PodSecurity | Network |
|---|---|---|---|
| `edp-system` | control-plane services, OPA, ESO | restricted | allow ingress from gateway only |
| `edp-jobs` | Argo controller, Temporal workers | restricted | egress to sources + S3 |
| `edp-data` | Trino, Lakekeeper | restricted | ingress from BI/agents, egress S3 |
| `edp-observability` | OTel, Prometheus, Loki, Tempo, Grafana | baseline | egress none |
| `edp-security` | Kyverno, Falco, cert-manager | baseline | cluster-wide read |
| `tenant-<slug>` | tenant-scoped jobs, quotas, secrets | restricted | deny-all + explicit allows |

---

## 5.4 Local development (Docker Compose)

`deploy/docker-compose.yaml` brings up the core control plane and a working lakehouse on a laptop:

| Service | Port | Purpose |
|---|---|---|
| `postgres` | 5432 | All service schemas + Temporal + Lakekeeper |
| `redis` | 6379 | Cache, locks, rate limits |
| `minio` + `minio-init` | 9000/9001 | S3-compatible storage, buckets + lifecycle |
| `iceberg-rest` | 8181 | Iceberg REST catalog over MinIO |
| `trino` | 8080 | Query engine (Iceberg + Postgres catalogs) |
| `temporal` + `temporal-ui` | 7233/8088 | Durable execution |
| `keycloak` | 8081 | Local OIDC (realm + test users) |
| `opa` | 8182 | Policy decisions |
| `otel-collector` | 4317/4318 | Traces/metrics |
| `prometheus` + `grafana` | 9090/3000 | Metrics + dashboards (profile `obs`) |
| `mailpit` | 8025 | Notification testing |
| `localstack` (profile `aws`) | 4566 | Secrets Manager, SQS, KMS emulation |

Notes:

- **No cloud dependency for the core loop.** Connectors run as local processes via `edp connector run <spec>`,
  or as Compose services for the pull-based ones.
- Argo Workflows is *not* in the default profile; locally, `execution-bridge` runs jobs as subprocesses
  (`LocalExecutor`). This keeps laptop startup < 90 s. `--profile k8s` (k3d) enables the real Argo path.
- Seed script creates 3 tenants, 4 connections (mock SFTP/REST/Box/Drive), 6 datasets, 2 pipelines and sample
  documents so the UI is never empty.
- `make up`, `make seed`, `make test`, `make down`, `make logs`. `make reset` drops volumes.

---

## 5.5 Observability

### Signals

| Signal | Standard | Retention | Use |
|---|---|---|---|
| Traces | OTel, W3C `traceparent` propagated through gateway → Temporal → connector/Argo → S3 writes | 7 d (Tempo) | One trace per run; `run_id` as span attribute |
| Metrics | Prometheus, RED for services, USE for infra, domain metrics (`runs_total`, `queue_wait_seconds`, `bytes_ingested`) | 15 d raw / 13 mo downsampled | SLOs, autoscaling, capacity |
| Logs | JSON, `tenant_id`, `run_id`, `trace_id`, `level`, `component` | 30 d hot / 1 y cold | Debug, audit-adjacent |
| Audit | Separate append-only stream | 7 y | Compliance |
| Events | CloudEvents to bus | 30 d | Replay, integrations |

### Dashboards (per audience)

- **Executive:** data products live, freshness compliance, incidents, cost per tenant.
- **SRE:** error budget burn, API latency/errors, Temporal backlog, Argo queue depth, Karpenter churn.
- **Data engineer:** run success by pipeline, p50/p95 duration, SLA misses, top failing sources.
- **Steward:** catalog completeness, unclassified datasets, expiring grants, access request SLA.
- **Security:** denied decisions, break-glass, secret access, anomalous exports.

### Alerts (symptom-based, with runbooks)

| Alert | Condition | Severity |
|---|---|---|
| API error budget burn | 5% budget in 1 h | P1 |
| Run failure spike | > 10% failures over 15 min, ≥ 5 runs | P1 |
| SLA miss imminent | deadline − p95 duration < 0 | P2 |
| Queue wait | p95 > 10 min for 10 min | P2 |
| Connector auth failures | > 5 consecutive 401/403 for one connection | P2 |
| Catalog sync lag | OpenMetadata consumer lag > 15 min | P3 |
| Policy bundle stale | last successful load > 30 min | P2 |
| Disk/DB saturation | > 85% for 10 min | P2 |
| Spot interruption rate | > 20% of batch nodes per hour | P3 |

Every alert links to a runbook in `docs/runbooks/` (phase 1 deliverable) with diagnosis commands and rollback.

---

## 5.6 Backup, DR and business continuity

| Tier | Data | RPO | RTO | Mechanism |
|---|---|---|---|---|
| 0 | Control plane (Postgres), config, policies | 5 min | 1 h | Aurora Multi-AZ + PITR + cross-region global DB; config export to Git hourly |
| 1 | Gold/silver Iceberg, catalog metadata | 15 min | 4 h | S3 CRR + Lakekeeper metadata backup; OM Postgres replica |
| 2 | Bronze | 1 h | 24 h | S3 versioning; rebuild from raw if needed |
| 3 | Raw | 15 min | 24 h | S3 CRR + Object Lock |
| 4 | Search index, vectors | n/a | 48 h | Rebuild from Iceberg (vectors re-embedded) |

- **DR drills** quarterly: restore control plane into `prod-dr`, run a gold pipeline, validate BI connectivity.
- **Game days** twice a year: kill a connector mid-run, exhaust Kueue quota, expire an OAuth token, delete a
  dataset by mistake (restore path).
- **Runbooks** for: Temporal unavailable, Argo controller down, Trino coordinator loss, OpenMetadata down,
  certificate expiry, KMS key access loss, spot capacity exhaustion, ransomware/compromised credential.

---

## 5.7 Cost model

| Driver | Share (typical) | Levers |
|---|---|---|
| S3 storage | 30–40% | Lifecycle to Glacier IR, compaction, snapshot expiry, dedupe |
| Compute (Spark/Trino) | 25–35% | Spot, Kueue priorities, AQE, partition pruning, right-sizing |
| EKS control plane + platform nodes | 10% | Consolidation, one cluster per env, Graviton |
| Postgres/OpenSearch | 10% | Right-size, read replicas only where needed, index lifecycle |
| Network egress | 5–10% | Keep compute in-region, VPC endpoints, avoid cross-AZ shuffles |
| Observability | 5% | Sampling, retention tiers, cardinality limits |

**Showback:** every pod carries `tenant`, `cost_center`, `pipeline` labels; `usage-meter` joins pod-seconds,
S3 bytes and Trino query bytes into a monthly statement per tenant, exposed at `/v1/usage`. Target: platform
cost ≤ 15% of the value of data products it serves (tracked, not assumed).

---

## 5.8 Operational readiness checklist (go-live gate)

- [ ] SLOs defined, dashboards live, alerts routed to on-call with runbooks
- [ ] Backup restore tested in the last 30 days; DR drill passed
- [ ] Load test at 2× baseline passed (API + 1,000 concurrent runs)
- [ ] Chaos: pod kill, node drain, spot interruption, DB failover, source 429 storm
- [ ] Security: pen test closed, dependency scan clean, secrets rotation verified
- [ ] Policy tests cover every role × classification combination
- [ ] Tenant onboarding runbook + quota defaults + cost alerts
- [ ] Runbooks for top 10 failure modes reviewed by on-call
- [ ] Data retention jobs verified; legal hold tested
- [ ] Support model documented (L1/L2/L3, escalation, office hours)
