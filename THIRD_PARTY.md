# Third-Party Open-Source Inventory

Meridian prefers Apache-2.0, MIT and BSD-3-Clause dependencies. This inventory covers the reference
deployment. It is not legal advice; generate a complete SBOM (`syft`, `pip-audit`, `npm sbom`) and review it
before distribution.

## Runtime — platform

| Component | Version | Licence | Use |
|---|---|---|---|
| Python | 3.12 | PSF-2.0 | Runtime |
| FastAPI | 0.162 | MIT | HTTP API |
| Starlette | 1.10 | BSD-3-Clause | ASGI toolkit |
| Uvicorn | 0.54 | BSD-3-Clause | ASGI server |
| Pydantic / pydantic-settings | 2.14 / 2.16 | MIT | Validation/config |
| SQLAlchemy | 2.1 | MIT | ORM |
| pg8000 | 1.31 | BSD-3-Clause | PostgreSQL driver |
| DuckDB | 1.5 | MIT | Embedded SQL transforms |
| PyJWT | 2.15 | MIT | JWT |
| cryptography | 46 | Apache-2.0 OR BSD-3-Clause | OIDC/JWKS |
| httpx | 0.28 | BSD-3-Clause | HTTP client |
| croniter | 6.2 | MIT | Cron parsing |
| python-multipart | 0.0.33 | Apache-2.0 | Uploads |
| openpyxl | 3.1 | MIT | XLSX parsing |
| pypdf | 6.21 | BSD-3-Clause | PDF text |
| python-docx | 1.2 | MIT | DOCX parsing |
| defusedxml | 0.7 | PSF-2.0 | Safe XML |
| boto3 / botocore | 1.43 | Apache-2.0 | S3 / Secrets Manager |
| tzdata | 2026.6 | Apache-2.0 | IANA timezone data on Windows |
| OpenTelemetry SDK/API | 1.45 | Apache-2.0 | Traces/metrics |
| OTel OTLP HTTP exporter | 1.45 | Apache-2.0 | Export |
| OTel FastAPI/SQLAlchemy/HTTPX instrumentation | 0.66b | Apache-2.0 | Auto-instrumentation |
| pytest | 8.4 | MIT | Test only |
| ruff | 0.17 | MIT | Lint only |
| mypy | 1.20 | MIT | Types only |

## Runtime — web

| Component | Version | Licence | Use |
|---|---|---|---|
| Node.js | 22 | MIT | Web runtime |
| Next.js | 15.5.28 | MIT | React framework |
| React / React DOM | 19.1 | MIT | UI |
| @xyflow/react | 12.8 | MIT | DAG editor |
| lucide-react | 0.468 | ISC | Icons |
| TypeScript | 5.7 | Apache-2.0 | Build only |

## Infrastructure

| Component | Licence | Use / note |
|---|---|---|
| PostgreSQL 16 | PostgreSQL Licence (permissive) | Metadata/queue |
| SeaweedFS 3.80 | Apache-2.0 | Optional local S3-compatible store; chosen over AGPL MinIO |
| OpenTelemetry Collector Contrib | Apache-2.0 | Telemetry pipeline |
| Prometheus | Apache-2.0 | Metrics |
| Jaeger | Apache-2.0 | Traces |
| Kubernetes / Kustomize | Apache-2.0 | Orchestration |
| eksctl | Apache-2.0 | EKS provisioning |
| ingress-nginx | Apache-2.0 | Ingress |
| cert-manager | Apache-2.0 | Certificates |
| External Secrets Operator | Apache-2.0 | Secret sync |
| Keycloak (optional) | Apache-2.0 | Local identity design stack |
| OPA (optional) | Apache-2.0 | Policy design stack |
| Trino (optional) | Apache-2.0 | Query design stack |
| Apache Iceberg / Lakekeeper (optional) | Apache-2.0 | Lakehouse design stack |
| OpenMetadata (optional) | Apache-2.0 | Metadata design stack |
| Apache Airflow, dbt Core, Spark, Argo Workflows, Temporal (optional) | Apache-2.0 / MIT | Production orchestration stack |

## Optional extras (not installed by default)

| Component | Licence | Note |
|---|---|---|
| Paramiko | LGPL-2.1 | SFTP support (`.[sftp]`); isolate it in a separate image if LGPL is not acceptable |
| pymongo | Apache-2.0 | MongoDB connector (`.[mongo]`) |

## Deliberately excluded

| Component | Licence | Why |
|---|---|---|
| MinIO | AGPL-3.0 | Replaced by SeaweedFS for the local S3 profile |
| Grafana | AGPL-3.0 | Prometheus + Jaeger used; Grafana is optional and not bundled |
| Loki / Tempo | AGPL-3.0 | JSONL + OTLP + Jaeger cover the reference; use a managed service or separate deployment |
| Redis 7.4+ | RSALv2/SSPL | Not needed: the task queue lives in PostgreSQL |
| Airbyte | ELv2 (core) | Not bundled; triggered as an external system only |
| Elasticsearch | SSPL/Elastic Licence | Not bundled |

## Recommended SBOM and licence gates

```bash
# Python
uv export --project services/platform-api --format requirements-txt > /tmp/requirements.txt
pip-audit -r /tmp/requirements.txt
syft dir:services/platform-api -o spdx-json > sbom-platform.spdx.json

# Node
cd apps/web && npm sbom --sbom-format cyclonedx > ../../sbom-web.cdx.json
npm audit --omit=dev

# Container images
trivy image --scanners vuln,license ghcr.io/ORG/meridian-api:0.1.0
```

CI should fail on:

- a dependency licence outside the approved set;
- a critical/high vulnerability with a fix available;
- an unpinned base image or unsigned image in production manifests.

## Attribution

The reference product does not redistribute third-party source code. Container images include the packages
above; preserve their licence files and notices when distributing images or source. Apache-2.0 components
require retention of NOTICE files where present. This document lists the primary components and is not a
substitute for the licence texts shipped with each package.
