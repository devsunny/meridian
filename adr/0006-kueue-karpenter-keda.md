# ADR-0006: Kueue + Karpenter + KEDA for elastic, fair job execution

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** SRE, Platform Engineering, FinOps

## Context

Job execution must autoscale across four dimensions: pod replicas, job admission (multi-tenant quotas and fair
sharing), nodes (including spot), and engine-level workers (Spark executors, Trino workers). Without admission
control, one team's backfill starves the nightly SLA runs; without spot, batch cost is 3× higher; without
queue-driven scaling, connector pods sit idle.

Candidates: Cluster Autoscaler + namespaces + ResourceQuota; Karpenter + KEDA; Kueue; Volcano; Airflow pools;
a custom queue in the control plane.

## Decision

- **KEDA** for queue/backlog-driven pod autoscaling (connector pools, Temporal workers, doc processors), with
  HPA for request-driven services.
- **Kueue** for batch job admission: `ClusterQueue` per tenant class, cohorts for borrowing, priorities,
  preemption, and per-tenant nominal quotas.
- **Karpenter** for node provisioning: separate NodePools for system, platform, spot batch, on-demand batch and
  GPU; consolidation on; spot ratio target 60–70% for batch.
- **Spark dynamic allocation** for engine-level elasticity, bounded by the tenant's Kueue quota.
- Kueue is the **only** admission path for `edp-jobs`; direct pod creation is blocked by Kyverno.

## Rationale

- `ResourceQuota` alone is static and cannot express fair sharing or borrowing between tenants; Kueue adds
  queueing, preemption and cohort semantics that match how enterprises actually allocate batch capacity.
- Karpenter provisions the right instance type in ~60 s (vs. node-group autoscaling in minutes), which is what
  makes spot viable for short jobs.
- KEDA's scale-to-zero for connector pools cuts idle cost dramatically (most connectors run a few times a day).
- Volcano is powerful but heavier and oriented to HPC-style gang scheduling; Kueue integrates cleanly with
  K8s `Job`/`JobSet` and Argo.

## Consequences

**Positive**
- SLA-bearing jobs get capacity ahead of backfills via priority + preemption.
- 60%+ of batch CPU on spot without sacrificing correctness (checkpointing required).
- Idle connector capacity costs ~zero.
- Quotas are declarative and auditable; chargeback maps to ClusterQueues.

**Negative / accepted**
- Three extra controllers to operate and tune; Kueue and Karpenter version compatibility must be managed.
- Spot interruptions require every batch workload to checkpoint or tolerate restart — enforced in the
  connector SDK and Spark templates, but custom containers can still get it wrong.
- Kueue's preemption can surprise users; the UI must show queue position and preemption history.
- Cold starts (25 s for connector pods) must be hidden by prefetching/warm pools for latency-sensitive sources.

## Alternatives considered

1. **Cluster Autoscaler + node groups + ResourceQuota.** Simpler, but slower scale-up, no fair sharing, no
   preemption; spot utilization suffers.
2. **Volcano.** Strong gang scheduling and queues; more complex, smaller community for our use case.
3. **Airflow pools / custom queue in `orchestrate`.** Would duplicate K8s admission and lose node-level
   integration; rejected.
4. **Dedicated clusters per tenant.** Excellent isolation, 5–10× cost; reserved for the `dedicated` tier only.

## Compliance

Quarterly review of spot interruption rate, queue wait p95 and quota utilization. If p95 queue wait for
tier-1 pipelines exceeds 2 minutes at baseline load, raise `gold` nominal quota or introduce a reserved pool.
