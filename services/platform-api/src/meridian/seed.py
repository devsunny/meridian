from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from edp_connector_sdk import RawAsset
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import write_audit
from .config import get_settings
from .context import request_context, utcnow
from .engine.dag import next_run_time
from .logging_setup import get_logger
from .models import (
    AccessRequest,
    Connection,
    ExternalSystem,
    Ingestion,
    Pipeline,
    PipelineVersion,
    Schedule,
    Tenant,
    User,
)
from .parsers import parse_asset
from .security import hash_password
from .services.datasets import add_lineage, save_dataset

logger = get_logger("meridian.seed")
settings = get_settings()

ORDERS = [
    ["SO-1001", "C-100", "2026-10-01", "North America", "online", 1840.00, "completed"],
    ["SO-1002", "C-101", "2026-10-01", "Europe", "partner", 920.50, "completed"],
    ["SO-1003", "C-102", "2026-10-02", "Asia Pacific", "online", 2310.75, "completed"],
    ["SO-1004", "C-103", "2026-10-03", "North America", "field", 480.00, "completed"],
    ["SO-1005", "C-104", "2026-10-04", "Europe", "online", 1250.25, "completed"],
    ["SO-1006", "C-105", "2026-10-05", "Latin America", "partner", 760.10, "completed"],
    ["SO-1007", "C-100", "2026-10-06", "North America", "online", 3120.00, "completed"],
    ["SO-1008", "C-106", "2026-10-07", "Asia Pacific", "field", 980.40, "completed"],
    ["SO-1009", "C-107", "2026-10-08", "Europe", "partner", 1420.00, "refunded"],
    ["SO-1010", "C-101", "2026-10-09", "Europe", "online", 660.80, "completed"],
    ["SO-1011", "C-108", "2026-10-10", "North America", "online", 2100.00, "completed"],
    ["SO-1012", "C-109", "2026-10-11", "Asia Pacific", "partner", 1180.30, "completed"],
    ["SO-1013", "C-102", "2026-10-12", "Asia Pacific", "online", 780.00, "completed"],
    ["SO-1014", "C-110", "2026-10-13", "Latin America", "field", 540.90, "completed"],
    ["SO-1015", "C-103", "2026-10-14", "North America", "partner", 1960.60, "completed"],
    ["SO-1016", "C-111", "2026-10-15", "Europe", "online", 440.00, "completed"],
    ["SO-1017", "C-104", "2026-10-16", "Europe", "online", 2870.45, "completed"],
    ["SO-1018", "C-112", "2026-10-17", "Asia Pacific", "partner", 1350.00, "completed"],
    ["SO-1019", "C-105", "2026-10-18", "Latin America", "online", 890.20, "completed"],
    ["SO-1020", "C-106", "2026-10-19", "Asia Pacific", "field", 1650.00, "completed"],
    ["SO-1021", "C-113", "2026-10-20", "North America", "online", 3020.00, "completed"],
    ["SO-1022", "C-107", "2026-10-21", "Europe", "partner", 740.75, "completed"],
    ["SO-1023", "C-108", "2026-10-22", "North America", "field", 520.00, "completed"],
    ["SO-1024", "C-109", "2026-10-23", "Asia Pacific", "online", 1430.10, "completed"],
]

CUSTOMERS = [
    {"customer_id": "C-100", "full_name": "Jordan Ellis", "email": "jordan.ellis@example.com", "phone": "+1 415 555 0132", "country": "US"},
    {"customer_id": "C-101", "full_name": "Amelie Laurent", "email": "amelie.laurent@example.fr", "phone": "+33 6 12 34 56 78", "country": "FR"},
    {"customer_id": "C-102", "full_name": "Kenji Watanabe", "email": "kenji.watanabe@example.jp", "phone": "+81 90 1234 5678", "country": "JP"},
    {"customer_id": "C-103", "full_name": "Sofia Reyes", "email": "sofia.reyes@example.mx", "phone": "+52 55 1234 5678", "country": "MX"},
    {"customer_id": "C-104", "full_name": "Lena Fischer", "email": "lena.fischer@example.de", "phone": "+49 151 23456789", "country": "DE"},
    {"customer_id": "C-105", "full_name": "Mateo Silva", "email": "mateo.silva@example.br", "phone": "+55 11 91234 5678", "country": "BR"},
    {"customer_id": "C-106", "full_name": "Priya Nair", "email": "priya.nair@example.in", "phone": "+91 98765 43210", "country": "IN"},
    {"customer_id": "C-107", "full_name": "Oliver Grant", "email": "oliver.grant@example.co.uk", "phone": "+44 7700 900123", "country": "GB"},
]

DOC_TEXT = """Refund and return policy (2026)

Customers may request a refund within 30 days of delivery. The order must be in its original condition and include the original packaging. Refunds are issued to the original payment method within five to seven business days after the return is inspected.

Damaged or defective items are eligible for a full refund or replacement within 90 days. Customers should attach a photograph of the damage to the support ticket. Shipping charges are refunded when the fault is ours.

Digital products are non-refundable after activation, except where required by local consumer protection law. Enterprise customers with a negotiated agreement follow the terms in that agreement, which take precedence over this policy.

Approval thresholds: support agents may approve refunds up to 500 USD. A support lead must approve refunds from 500 to 2,500 USD. Finance approval is required above 2,500 USD or for any refund older than 60 days.

Customers in the European Union have a statutory 14-day right of withdrawal for distance sales. The statutory right applies even when the standard policy window has closed, where the product is eligible.

Data handling: support tickets contain personal data and are classified CONFIDENTIAL. Agents must not copy customer data into external tools. Access to the refund analytics dataset requires an approved data access grant.
"""


def _write_samples() -> Path:
    sample_dir = Path(settings.storage_root).expanduser().resolve().parent / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    orders_path = sample_dir / "orders.csv"
    with orders_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["order_id", "customer_id", "order_date", "region", "channel", "amount", "status"])
        writer.writerows(ORDERS)
    (sample_dir / "customers.json").write_text(json.dumps(CUSTOMERS, indent=2), encoding="utf-8")
    (sample_dir / "refund-policy.md").write_text(DOC_TEXT, encoding="utf-8")
    docx_path = sample_dir / "refund-policy.docx"
    if not docx_path.exists():
        try:
            import docx

            document = docx.Document()
            document.add_heading("Refund and return policy", level=1)
            for paragraph in DOC_TEXT.split("\n\n"):
                document.add_paragraph(paragraph)
            document.save(docx_path)
        except Exception:  # noqa: BLE001
            docx_path = sample_dir / "refund-policy.md"
    return sample_dir


def _parse_raw(path: Path) -> Any:
    content = path.read_bytes()
    from mimetypes import guess_type

    from .connectors.utils import guess_media_type

    return parse_asset(
        RawAsset(
            filename=path.name,
            content=content,
            media_type=guess_type(path.name)[0] or guess_media_type(path.name),
            source_uri=str(path),
        )
    )


def seed_demo_data(session: Session) -> None:
    existing = session.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one_or_none()
    if existing:
        return
    with request_context(request_id="req_seed_demo_000000000001"):
        sample_dir = _write_samples()
        tenant = Tenant(id="ten_acme", slug="acme", name="Acme Analytics", isolation_tier="shared")
        session.add(tenant)
        session.flush()
        account_password = settings.demo_password
        users = [
            User(
                id="usr_admin",
                tenant_id=tenant.id,
                email="admin@meridian.local",
                name="Avery Chen",
                role="admin",
                password_hash=hash_password(account_password),
            ),
            User(
                id="usr_steward",
                tenant_id=tenant.id,
                email="steward@meridian.local",
                name="Priya Raman",
                role="steward",
                password_hash=hash_password(account_password),
            ),
            User(
                id="usr_engineer",
                tenant_id=tenant.id,
                email="engineer@meridian.local",
                name="Noah Williams",
                role="engineer",
                password_hash=hash_password(account_password),
            ),
            User(
                id="usr_analyst",
                tenant_id=tenant.id,
                email="analyst@meridian.local",
                name="Mia Alvarez",
                role="analyst",
                password_hash=hash_password(account_password),
            ),
            User(
                id="usr_auditor",
                tenant_id=tenant.id,
                email="auditor@meridian.local",
                name="Sam Okafor",
                role="auditor",
                password_hash=hash_password(account_password),
            ),
        ]
        session.add_all(users)
        session.flush()

        orders_connection = Connection(
            id="con_sales_csv",
            tenant_id=tenant.id,
            name="Sales CSV landing",
            type="file",
            description="Daily sales export dropped by the commerce team.",
            config={"root": str(sample_dir), "path": str(sample_dir / "orders.csv")},
            owner="engineer@meridian.local",
            last_tested_at=utcnow(),
            last_test_ok=True,
        )
        docs_connection = Connection(
            id="con_policy_docx",
            tenant_id=tenant.id,
            name="Support policy documents",
            type="file",
            description="Unstructured support and policy documents from the shared drive.",
            config={"root": str(sample_dir), "path": str(sample_dir / "refund-policy.docx")},
            owner="steward@meridian.local",
            last_tested_at=utcnow(),
            last_test_ok=True,
        )
        pii_connection = Connection(
            id="con_customers_json",
            tenant_id=tenant.id,
            name="Customer master (JSON)",
            type="file",
            description="CRM customer master export containing personal data.",
            config={"root": str(sample_dir), "path": str(sample_dir / "customers.json")},
            owner="steward@meridian.local",
            last_tested_at=utcnow(),
            last_test_ok=True,
        )
        session.add_all([orders_connection, docs_connection, pii_connection])
        session.flush()

        orders_raw = _parse_raw(sample_dir / "orders.csv")
        raw_dataset = save_dataset(
            session,
            tenant_id=tenant.id,
            name="sales_orders_raw",
            records=orders_raw.records,
            schema=orders_raw.schema,
            layer="bronze",
            description="Raw commerce orders landed from the daily CSV export.",
            classification="internal",
            source_connection_id=orders_connection.id,
            source_uri=str(sample_dir / "orders.csv"),
            owner="engineer@meridian.local",
            extra_meta={"source_system": "commerce", "connector_type": "file"},
        )
        customers = _parse_raw(sample_dir / "customers.json")
        customer_dataset = save_dataset(
            session,
            tenant_id=tenant.id,
            name="customer_pii_master",
            records=customers.records,
            schema=customers.schema,
            layer="bronze",
            description="CRM customer master containing names, emails and phone numbers.",
            classification="restricted",
            source_connection_id=pii_connection.id,
            source_uri=str(sample_dir / "customers.json"),
            owner="steward@meridian.local",
        )
        doc_asset = _parse_raw(sample_dir / "refund-policy.docx")
        document_dataset = save_dataset(
            session,
            tenant_id=tenant.id,
            name="support_knowledge",
            records=doc_asset.records,
            schema=doc_asset.schema,
            layer="raw",
            description="Governed support policies, chunked for retrieval and citation.",
            classification="internal",
            source_connection_id=docs_connection.id,
            source_uri=str(sample_dir / "refund-policy.docx"),
            owner="steward@meridian.local",
            document=True,
        )

        gold_records = _gold_records()
        from .parsers import infer_schema, profile_records

        gold_schema = infer_schema(gold_records)
        gold = save_dataset(
            session,
            tenant_id=tenant.id,
            name="gold_sales_summary",
            records=gold_records,
            schema=gold_schema,
            layer="gold",
            description="Monthly revenue by region and channel, refreshed by the Customer Revenue Daily pipeline.",
            classification="internal",
            owner="analyst@meridian.local",
            source_uri="pipeline://customer-revenue-daily",
        )
        gold.profile = profile_records(gold_records, gold_schema)
        session.add(gold)
        add_lineage(
            session,
            tenant_id=tenant.id,
            from_dataset_id=raw_dataset.id,
            to_dataset_id=gold.id,
            run_id=None,
            task_id="seed",
            operation="seed.aggregate",
            request_id="req_seed_demo_000000000001",
        )

        sales_ingestion = Ingestion(
            id="ing_sales_orders",
            tenant_id=tenant.id,
            name="Daily sales orders",
            description="Land the commerce CSV, validate schema and register lineage.",
            connection_id=orders_connection.id,
            target_dataset="sales_orders_raw",
            spec={
                "resource": str(sample_dir / "orders.csv"),
                "classification": "internal",
                "layer": "bronze",
                "options": {"max_bytes": 52428800},
            },
            schedule_cron="0 2 * * *",
            schedule_timezone="America/New_York",
            owner="engineer@meridian.local",
        )
        docs_ingestion = Ingestion(
            id="ing_support_docs",
            tenant_id=tenant.id,
            name="Support knowledge ingestion",
            description="Parse policy documents, extract text, chunk and index for RAG.",
            connection_id=docs_connection.id,
            target_dataset="support_knowledge",
            spec={
                "resource": str(sample_dir / "refund-policy.docx"),
                "classification": "internal",
                "layer": "raw",
                "options": {"max_bytes": 52428800},
            },
            schedule_cron="30 2 * * *",
            schedule_timezone="America/New_York",
            owner="steward@meridian.local",
        )
        pii_ingestion = Ingestion(
            id="ing_customer_master",
            tenant_id=tenant.id,
            name="Customer master restricted landing",
            description="Restricted PII landing with automatic classification.",
            connection_id=pii_connection.id,
            target_dataset="customer_pii_master",
            spec={
                "resource": str(sample_dir / "customers.json"),
                "classification": "restricted",
                "layer": "bronze",
            },
            owner="steward@meridian.local",
        )
        session.add_all([sales_ingestion, docs_ingestion, pii_ingestion])
        session.flush()

        pipeline = Pipeline(
            id="pip_customer_revenue",
            tenant_id=tenant.id,
            name="Customer Revenue Daily",
            description="Bronze orders → conformed silver → quality gate → gold revenue summary.",
            owner="engineer@meridian.local",
            current_version=1,
            dag={
                "nodes": [
                    {
                        "id": "land_orders",
                        "name": "Land orders",
                        "type": "ingestion.run",
                        "config": {"ingestion_id": sales_ingestion.id},
                        "depends_on": [],
                        "position": {"x": 40, "y": 180},
                    },
                    {
                        "id": "clean_orders",
                        "name": "Clean & conform",
                        "type": "sql.transform",
                        "config": {
                            "sql": "SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, region, channel, amount, status FROM input WHERE amount > 0",
                            "target_dataset": "silver_sales_orders",
                            "layer": "silver",
                        },
                        "depends_on": ["land_orders"],
                        "position": {"x": 320, "y": 180},
                    },
                    {
                        "id": "quality_gate",
                        "name": "Revenue quality gate",
                        "type": "quality.check",
                        "config": {
                            "min_rows": 10,
                            "required_columns": ["order_id", "region", "amount"],
                            "unique_column": "order_id",
                        },
                        "depends_on": ["clean_orders"],
                        "position": {"x": 600, "y": 180},
                        "breakpoint": False,
                    },
                    {
                        "id": "publish_gold",
                        "name": "Publish gold revenue",
                        "type": "sql.transform",
                        "config": {
                            "sql": "SELECT region, channel, date_trunc('month', order_date) AS month, count(*) AS orders, sum(amount) AS revenue FROM input WHERE status = 'completed' GROUP BY 1, 2, 3 ORDER BY revenue DESC",
                            "target_dataset": "gold_sales_summary",
                            "layer": "gold",
                        },
                        "depends_on": ["quality_gate"],
                        "position": {"x": 880, "y": 180},
                        "breakpoint": False,
                    },
                ],
                "edges": [
                    {"source": "land_orders", "target": "clean_orders"},
                    {"source": "clean_orders", "target": "quality_gate"},
                    {"source": "quality_gate", "target": "publish_gold"},
                ],
            },
        )
        session.add(pipeline)
        session.flush()
        session.add(
            PipelineVersion(
                tenant_id=tenant.id,
                pipeline_id=pipeline.id,
                version=1,
                dag=pipeline.dag,
                created_by="admin@meridian.local",
                request_id="req_seed_demo_000000000001",
            )
        )
        session.add_all(
            [
                Schedule(
                    tenant_id=tenant.id,
                    name="Daily sales landing",
                    target_type="ingestion",
                    target_id=sales_ingestion.id,
                    cron="0 2 * * *",
                    timezone="America/New_York",
                    next_run_at=next_run_time("0 2 * * *", "America/New_York", datetime.now(UTC)),
                    max_concurrent_runs=1,
                ),
                Schedule(
                    tenant_id=tenant.id,
                    name="Customer Revenue Daily",
                    target_type="pipeline",
                    target_id=pipeline.id,
                    cron="0 6 * * *",
                    timezone="America/New_York",
                    next_run_at=next_run_time("0 6 * * *", "America/New_York", datetime.now(UTC)),
                    max_concurrent_runs=1,
                ),
                ExternalSystem(
                    tenant_id=tenant.id,
                    name="Airflow (production)",
                    type="airflow",
                    base_url="http://airflow.example.internal:8080",
                    secret_ref=None,
                    config={"dag_id": "legacy_customer_360"},
                    enabled=False,
                    status="configured",
                ),
                AccessRequest(
                    tenant_id=tenant.id,
                    requester_id="usr_analyst",
                    requester_email="analyst@meridian.local",
                    dataset_id=customer_dataset.id,
                    action="read",
                    purpose="Build a churn analysis for the customer success team. PII will stay in the governed workspace.",
                    duration_days=14,
                    status="PENDING",
                    expires_at=datetime.now(UTC) + timedelta(days=14),
                ),
            ]
        )
        write_audit(
            session,
            tenant_id=tenant.id,
            action="system.seeded",
            resource_type="tenant",
            resource_id=tenant.id,
            actor_id="system",
            actor_email="system",
            data={
                "datasets": [raw_dataset.id, customer_dataset.id, document_dataset.id, gold.id],
                "pipeline": pipeline.id,
                "note": "Demo tenant provisioned with sample relational, JSON and DOCX data.",
            },
        )
        session.flush()
        logger.info(
            "demo_seeded",
            extra={"tenant": tenant.slug, "datasets": 4, "pipeline": pipeline.id, "users": len(users)},
        )


def _gold_records() -> list[dict[str, Any]]:
    from collections import defaultdict

    groups: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    for _order_id, _customer, order_date, region, channel, amount, status in ORDERS:
        if status != "completed":
            continue
        key = (region, channel, order_date[:7] + "-01")
        groups[key]["orders"] += 1
        groups[key]["revenue"] += float(amount)
    return [
        {
            "region": region,
            "channel": channel,
            "month": month,
            "orders": int(values["orders"]),
            "revenue": round(values["revenue"], 2),
        }
        for (region, channel, month), values in groups.items()
    ]
