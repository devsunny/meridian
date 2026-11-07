# ADR-0003: Temporal for durable state, Argo Workflows for batch DAGs

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** Platform Engineering, Data Engineering, SRE

## Context

The platform needs two kinds of execution that look similar in a UI but are fundamentally different:

1. **Long-running, stateful operations**: an ingestion that takes 6 hours, hits rate limits, needs retries with
   backoff, waits for a human approval, survives pod eviction, and must know exactly where it stopped.
2. **Container DAGs**: a nightly pipeline with 20 steps (Spark, dbt, quality gate, publish) where each step is a
   pod with resource requirements and data dependencies.

Candidate stacks: Airflow for both; Temporal only; Argo Workflows only; Temporal + Argo; Step Functions.

## Decision

Use **both**, with a strict ownership boundary:

- **Temporal** owns durable state, retries with backoff, timers (including multi-day), human-in-the-loop signals,
  compensation/sagas, and per-entity lifecycle (ingestion runs, access requests, config promotion, ACL sync).
- **Argo Workflows** owns multi-step container DAG execution, per-step pods, artifact passing and K8s-native
  parallelism.
- **One scheduler** (`orchestrate`) drives both; Argo `CronWorkflow` and Temporal cron are prohibited.
- Temporal workflows may submit and await Argo Workflows. Argo never starts Temporal workflows.
- `orchestrate`'s database is the system of record for run state; both engines are reconciled into it.

## Rationale

- Argo has no durable timer or signal semantics; modeling approvals or 3-day waits in Argo means a controller
  with a database — i.e., building Temporal badly.
- Temporal is not a data-plane DAG engine: it has no artifact passing, no per-step pod scheduling, no Spark
  integration. Modeling a 20-step Spark pipeline in Temporal means building Argo badly.
- Airflow could do both, but its scheduler is a central bottleneck for multi-tenant fairness, its Kubernetes
  executor is heavier to operate, and its durable-state model (retry the whole task) is weaker for sagas and
  human steps. It remains a fine choice for teams already standardized on it — not for a greenfield platform
  with these requirements.

## Consequences

**Positive**
- Each concern is handled by the engine designed for it.
- Temporal gives exactly-once-ish workflow semantics and replayable history for free.
- Argo gives rich K8s scheduling, per-step resources and a UI for step-level debugging.

**Negative / accepted**
- Two systems to operate, upgrade and monitor; two failure modes; two mental models for engineers.
- Risk of split-brain state if the boundary is violated. Mitigated by code review, the ownership table in
  doc 03, a reconciliation job, and an architecture test that fails if Argo code calls Temporal.
- More complex local development: `LocalExecutor` replaces Argo on laptops; Temporal still runs in Compose.

## Alternatives considered

1. **Argo only** (with a Postgres side-table for approvals/timers). Rejected: reimplements durable execution.
2. **Temporal only** (each DAG step as an activity that launches a pod). Rejected: no artifact graph, poor
   visibility of step dependencies, and activities are not designed for multi-hour pod lifecycles.
3. **Airflow 3 only.** Viable. Rejected for multi-tenant fairness, K8s-native scheduling and durable-signal
   requirements; revisit if the team's Airflow expertise outweighs the architectural fit.

## Compliance

The boundary is enforceable: `orchestrate` exposes `ExecutionPort` with two adapters; a lint rule forbids Argo
types in Temporal workflow code and vice versa. Revisit if Temporal or Argo changes licensing or if either
project stalls for > 12 months.
