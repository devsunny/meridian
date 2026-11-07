# 10. SOC 2 Readiness — Control Mapping and Evidence

> **Important:** this is a self-assessment mapping for the reference product. It is **not** a SOC 2 Type I
> or Type II report, not an audit opinion, and not a certification. A SOC 2 report is issued by an
> independent CPA firm after an examination of the organization's controls over a period. The code can
> produce evidence; it cannot establish the organizational, HR, vendor-management and physical controls the
> Trust Services Criteria require.

The mapping uses the AICPA 2017 Trust Services Criteria (TSC) as amended. The reference product is scoped to
the **Security** common criteria; availability, processing integrity, confidentiality and privacy controls
are partially addressed by architecture and must be completed for a real report.

---

## 10.1 System boundary

| In scope | Out of scope (customer / platform team responsibility) |
|---|---|
| Meridian API, scheduler, worker, web console | Corporate IdP configuration, MFA policy, joiner/mover/leaver |
| PostgreSQL metadata/queue/audit | Database patching, backups, encryption configuration, PITR |
| Local/S3 lake and document chunks | S3 bucket policy, KMS keys, Object Lock, lifecycle |
| OTel/Prometheus/JSONL telemetry | SIEM retention, alert routing, on-call, incident response |
| Docker/Kubernetes deployment manifests | Cluster hardening, node patching, VPC design, WAF, DDoS |
| Application authorization and audit | Background checks, security training, vendor risk assessments |

The production design (docs 01–08) covers the broader control environment. The reference deployment runs
single-tenant by default; tenant isolation is application-enforced, with Postgres RLS listed as a gap.

---

## 10.2 Common criteria mapping

| TSC | Control objective | Implemented evidence | Status | Gap / owner |
|---|---|---|---|---|
| CC1.1 | Integrity and ethical values | Code of conduct not shipped; engineering standards in doc 08 | Organizational | HR/security owner |
| CC1.2 | Board/management oversight | Executive roadmap and ADRs | Organizational | Leadership |
| CC1.3 | Roles and responsibilities | Six technical roles, ownership fields on datasets/pipelines | Partial | RACI and job descriptions |
| CC1.4 | Competence | Test suite, ADRs, runbooks, connector SDK docs | Partial | Training records |
| CC1.5 | Accountability | Audit chain with actor, action, resource, request ID | Configured | Performance reviews |
| CC2.1 | Information quality | Immutable dataset/pipeline versions; schema/profile metadata | Configured | Data quality SLAs |
| CC2.2 | Internal communication | Run monitor, notifications, access requests | Configured | On-call/notification policy |
| CC2.3 | External communication | OpenAPI, public docs, status endpoint | Partial | Customer status page |
| CC3.1 | Risk identification | ADRs record trade-offs; gap register in doc 09 | Partial | Formal risk assessment |
| CC3.2 | Risk assessment | Threat model referenced in design; no formal model in repo | Partial | Security architect |
| CC3.3 | Fraud risk | Audit, segregation of duties by role | Partial | Fraud risk workshop |
| CC3.4 | Change risk | Versioned DAGs, immutable pipeline versions, audit | Configured | Change advisory board |
| CC4.1 | Monitoring | Prometheus metrics, OTel traces, health probes | Configured | Alerting rules + on-call |
| CC4.2 | Deficiency evaluation | Error taxonomy, run failure states, audit | Partial | Incident/postmortem process |
| CC5.1 | Control selection | This mapping + design docs | Partial | Formal control catalog |
| CC5.2 | Technology controls | RBAC, secrets, hash-chained audit, tenant scoping | Configured | RLS, key management |
| CC5.3 | Policies and procedures | Architecture and runbook docs | Partial | Signed policy set |
| CC6.1 | Logical access — least privilege | Six roles; `require()` on mutations; tenant-filtered queries; scoped grants | Configured | API key scopes, JIT access |
| CC6.2 | Registration/authorization | Login, API keys, access requests + approvals | Configured | SCIM, MFA enforcement |
| CC6.3 | Role modification/removal | User create/update, last-admin guard, self-deactivation guard, audit | Configured | Automated access reviews |
| CC6.4 | Physical access | Cloud provider responsibility | Inherited | AWS evidence |
| CC6.5 | Disposal | Dataset versions, retention policy; no purge UI | Partial | Retention jobs + certificates |
| CC6.6 | External threats | CORS allowlist, security headers, no stack traces, rate limit | Partial | WAF, pen test, SAST/DAST |
| CC6.7 | Data transmission | TLS at ingress (EKS guide); OTLP HTTP; S3 HTTPS | Partial | Enforce TLS, mTLS for remote agent |
| CC6.8 | Malicious software | Non-root, read-only FS, dropped capabilities, pinned images | Partial | Image signing, admission policy |
| CC7.1 | Detection | JSONL logs with request/trace ID, audit events, Prometheus | Configured | SIEM + detections |
| CC7.2 | Monitoring | Health/readiness, run states, task metrics | Configured | SLOs and alerting |
| CC7.3 | Incident response | Runbook section, audit trail | Partial | IR plan, tabletop, paging |
| CC7.4 | Incident remediation | Retry, cancel, resume, replay from raw | Partial | Formal RCA process |
| CC7.5 | Recovery | Replayable raw data; Postgres/object-store backups (external) | Partial | Tested DR, RTO/RPO |
| CC8.1 | Change management | Immutable pipeline versions, audit, Kustomize/GitOps-ready | Configured | PR approvals, CI gates, Argo CD |
| CC9.1 | Risk mitigation | Vendor/license inventory, dependency choices | Partial | Vendor risk program |
| CC9.2 | Vendor management | OSS inventory, permissive licenses | Partial | Contracts/DPAs |

---

## 10.3 Evidence map

| Evidence | Where to obtain it |
|---|---|
| Authentication and role assignment | `GET /api/v1/security/users`, `/security/roles`; audit `user.created`, `auth.login` |
| Least-privilege enforcement | `require()` permission table; integration test that analyst cannot create pipelines |
| Access provisioning | `GET /api/v1/governance/access-requests`, `/grants`; audit `access.approved`, `access.revoked` |
| Data access record | audit `data.previewed`, `data.queried`, `data.downloaded` with dataset, actor and request ID |
| Change history | `GET /api/v1/pipelines/{id}/versions`; immutable `DatasetVersion` |
| Audit integrity | `GET /api/v1/governance/audit/verify` returns valid, checked count, head hash |
| Logging | service JSONL at `$MERIDIAN_LOG_DIR/{service}.jsonl`; per-run logs at `runs/{tenant}/{run}.jsonl` |
| Monitoring | `/metrics`, `/health/live`, `/health/ready`; OTel collector pipeline |
| Data classification | `/governance/classifications`; schema `pii` flags |
| Secret handling | connection records contain only `env:`/`aws-sm:`/`file:` references; API redaction |
| Deployment hardening | `deploy/k8s` security contexts, NetworkPolicy, HPA/PDB |
| Backup/DR | RDS PITR, S3 versioning/CRR (documented in EKS guide; configuration external) |

**Audit verification command**

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://meridian.example.com/api/v1/governance/audit/verify
```

Expected:

```json
{"valid": true, "checked": 128, "head_hash": "…", "message": "Audit chain verified."}
```

A broken chain returns `valid:false` and `broken_at_seq`. Treat that as a security incident: preserve the
database, compare with backups, and do not delete audit rows.

---

## 10.4 Control operation schedule (proposed)

| Frequency | Activity | Owner | Evidence |
|---|---|---|---|
| Every deploy | Change ticket + pipeline version diff + CI test result | Platform eng | Git/CI, audit |
| Daily | Review failed runs, auth anomalies, access requests | Platform on-call | Dashboard, logs |
| Weekly | Review active grants and expiring keys | Security/steward | `/grants`, `/api-keys` |
| Monthly | Access review: users, roles, service accounts | Security | Signed review |
| Monthly | Dependency and image vulnerability scan | Platform eng | pip-audit/npm audit/ECR scan |
| Quarterly | Restore test, DR tabletop, incident tabletop | SRE/security | Test report |
| Quarterly | Vendor/OSS license review | Legal/security | `THIRD_PARTY.md` |
| Annual | SOC 2 audit / pen test | Compliance | External report |

---

## 10.5 Segregation of duties

| Action | admin | steward | engineer | analyst | auditor |
|---|---|---|---|---|---|
| Create source/ingestion/pipeline | ✓ | ✓ | ✓ | — | — |
| Run pipeline | ✓ | ✓ | ✓ | — | — |
| Approve access request | ✓ | ✓ | — | — | — |
| Request access | ✓ | ✓ | ✓ | ✓ | — |
| Read restricted rows | ✓ (break-glass) | grant required | grant required | grant required | — |
| Read audit | ✓ | ✓ | — | — | ✓ |
| Manage users/API keys | ✓ | — | — | — | — |
| Change classification | ✓ | ✓ | ✓ (catalog write) | — | — |

The last active administrator cannot be demoted or self-deactivated (enforced in `/security/users`).

---

## 10.6 Logging and monitoring controls

- **One request ID per unit of work** is mandatory. Inbound IDs are accepted only if they match
  `[A-Za-z0-9_.:-]{8,128}`; otherwise the platform generates one. Runs reuse the inbound ID.
- **No secrets in logs.** Connector errors are sanitized; connection configs are redacted; the platform
  never logs passwords, tokens or full row payloads.
- **Sensitive data access is audited** at preview/query/download. Audit stores a truncated SQL statement,
  not result rows.
- **Metrics are low-cardinality** (method/status/type; no tenant ID labels). High-cardinality correlation lives
  in logs/traces.
- **Log retention** is a deployment policy. The reference defaults are 90 days hot for operational logs and
  7 years for exported audit events; implement S3 Object Lock before relying on the latter.

---

## 10.7 Security testing coverage

| Test | Reference |
|---|---|
| Cross-tenant access | Application filters; add a negative test per new route |
| Analyst privilege escalation | Integration test asserts 403 on pipeline create |
| Restricted data without grant | Integration test asserts 403 on preview |
| Grant approval and expiry | Integration test approves then previews; expiry logic in `active_grant` |
| Audit tamper detection | Verify endpoint; test asserts valid chain |
| DAG cycle / unsafe SQL | `DagSpec` and `FORBIDDEN_SQL`; add property-based tests |
| Secret leakage | Redaction helper; add a log-capture test in CI |
| Container escape | Non-root, read-only FS, drop capabilities; add Kyverno/PSA in production |

Recommended next tests: cross-tenant fuzzing, SSRF allowlist for HTTP connector, path traversal (partially
covered by `within()`), zip bombs in XLSX/DOCX, PDF parser denial-of-service, SQL parser bypasses, WebSocket
authorization, session fixation, and dependency CVEs.

---

## 10.8 Limitations and auditor questions

An auditor will ask for evidence the repository does not provide:

1. Organization chart, board minutes, security awareness training records.
2. Signed information-security policy, risk assessment, vendor risk assessments.
3. Background-check and onboarding/offboarding evidence.
4. Production change tickets and approvals for the audit period.
5. Penetration test and remediation evidence.
6. Incident response plan, tabletop results, and actual incident records.
7. Backup restore tests and DR exercise results.
8. Cloud configuration evidence (AWS Config, Security Hub, GuardDuty, KMS policy, S3 Block Public Access).
9. Monitoring alert definitions and on-call response records.
10. Data processing agreements and subprocessor list.

The repository can supply application-level evidence (items 4, 6, 9 partially) and control design; the rest
must be produced by the operating organization.

---

## 10.9 Statement of scope for a future audit

A realistic first audit scope is the production Meridian service at one region, one tenant tier, with:

- AWS EKS, RDS PostgreSQL, S3 + KMS, EFS;
- Entra ID/Okta SSO with MFA and SCIM;
- External Secrets Operator + Secrets Manager;
- OTel → managed observability + SIEM;
- documented change management, incident response, backup/DR and access-review procedures.

Until those are operating for an observation window, describe the platform as **SOC 2-aligned** or
**SOC 2-ready**, never “SOC 2 certified.”
