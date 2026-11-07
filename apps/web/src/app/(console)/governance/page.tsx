"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, ArrowUpRight, Check, ClipboardCheck, Fingerprint, Lock, RefreshCw, ShieldCheck, UserCheck, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { classificationTone, dateTime, relativeTime } from "@/lib/format";
import type { AccessRequest, AuditEvent, GovernanceSummary, Soc2Report } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner } from "@/components/ui";
import { useAuth } from "@/components/AuthProvider";
import { useToast } from "@/components/ToastProvider";

type Tab = "requests" | "classifications" | "audit" | "soc2";

export default function GovernancePage() {
  const { user } = useAuth();
  const canApprove = !!user && (user.permissions.includes("*") || user.permissions.includes("governance:write"));
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("requests");
  const [summary, setSummary] = useState<GovernanceSummary | null>(null);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [classifications, setClassifications] = useState<{ columns: Array<Record<string, any>>; summary: Record<string, number> } | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [soc2, setSoc2] = useState<Soc2Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [decision, setDecision] = useState<{ request: AccessRequest; approve: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [canAudit, setCanAudit] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const results = await Promise.allSettled([
        api.get<GovernanceSummary>("/governance/summary"),
        api.get<AccessRequest[]>("/governance/access-requests"),
        api.get<{ columns: Array<Record<string, any>>; summary: Record<string, number> }>("/governance/classifications"),
        api.get<AuditEvent[]>("/governance/audit?limit=200"),
        api.get<Soc2Report>("/governance/soc2"),
      ]);
      const [summaryResult, requestsResult, classificationsResult, auditResult, soc2Result] = results;
      if (summaryResult.status === "rejected") throw summaryResult.reason;
      if (requestsResult.status === "rejected") throw requestsResult.reason;
      if (classificationsResult.status === "rejected") throw classificationsResult.reason;
      setSummary(summaryResult.value);
      setRequests(requestsResult.value);
      setClassifications(classificationsResult.value);
      if (auditResult.status === "fulfilled" && soc2Result.status === "fulfilled") {
        setAudit(auditResult.value);
        setSoc2(soc2Result.value);
        setCanAudit(true);
      } else {
        setAudit([]);
        setSoc2(null);
        setCanAudit(false);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function decide() {
    if (!decision) return;
    setBusy(true);
    try {
      await api.post(`/governance/access-requests/${decision.request.id}/${decision.approve ? "approve" : "deny"}`, { reason });
      toast.push(decision.approve ? "Grant provisioned with an expiry." : "Request denied.", "success");
      setDecision(null);
      setReason("");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    try {
      const result = await api.get<{ valid: boolean; checked: number; message: string }>("/governance/audit/verify");
      toast.push(`${result.message} (${result.checked} events)`, result.valid ? "success" : "error");
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  if (loading) return <Spinner label="Loading governance" />;
  if (error) return <InlineError message={error} />;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Trust"
        title="Governance"
        description="Classify data, approve time-bound access, verify the audit chain and evidence SOC 2 controls."
        actions={canAudit ? <Button variant="secondary" onClick={() => void verify()}><Fingerprint size={15} /> Verify audit chain</Button> : undefined}
      />

      <div className="governance-banner">
        <div className="gov-banner-icon"><ShieldCheck size={23} /></div>
        <div>
          <strong>{summary?.audit_chain.valid ? "Audit chain intact" : "Audit chain needs attention"}</strong>
          <span>{summary?.audit_chain.checked || 0} events · head <code>{summary?.audit_chain.head_hash?.slice(0, 20)}…</code> · tenant {user?.tenant_slug}</span>
        </div>
        <div className="gov-banner-stats">
          <span><strong>{summary?.pending_access_requests || 0}</strong> pending</span>
          <span><strong>{summary?.active_grants || 0}</strong> active grants</span>
          <span><strong>{summary?.pii_columns.length || 0}</strong> PII columns</span>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === "requests" ? "active" : ""}`} onClick={() => setTab("requests")}><UserCheck size={14} /> Access requests</button>
        <button className={`tab ${tab === "classifications" ? "active" : ""}`} onClick={() => setTab("classifications")}><Lock size={14} /> Classifications</button>
        {canAudit && <button className={`tab ${tab === "audit" ? "active" : ""}`} onClick={() => setTab("audit")}><Activity size={14} /> Audit log</button>}
        {canAudit && <button className={`tab ${tab === "soc2" ? "active" : ""}`} onClick={() => setTab("soc2")}><ClipboardCheck size={14} /> SOC 2 readiness</button>}
      </div>

      {tab === "requests" && (
        <section className="panel">
          <div className="panel-head">
            <div><h2>Access requests</h2><p>Grants are scoped to one dataset, one action, one principal and an expiry.</p></div>
            <Badge tone="warning">{requests.filter((item) => item.status === "PENDING").length} need review</Badge>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Requester</th><th>Dataset</th><th>Purpose</th><th>Duration</th><th>Status</th><th>Requested</th><th /></tr></thead>
              <tbody>
                {requests.map((request) => (
                  <tr key={request.id}>
                    <td><div className="cell-title">{request.requester_email}</div><div className="cell-sub">{request.action}</div></td>
                    <td>{request.dataset ? <><div className="cell-title">{request.dataset.name}</div><Badge tone={classificationTone(request.dataset.classification)}>{request.dataset.classification}</Badge></> : request.dataset_id}</td>
                    <td className="purpose-cell">{request.purpose}</td>
                    <td className="muted">{request.duration_days} days</td>
                    <td><Badge tone={request.status === "APPROVED" ? "success" : request.status === "DENIED" ? "danger" : "warning"} dot>{request.status.toLowerCase()}</Badge></td>
                    <td className="muted">{relativeTime(request.created_at)}</td>
                    <td className="row-actions">
                      {request.status === "PENDING" && canApprove && (
                        <>
                          <Button size="sm" variant="primary" onClick={() => { setDecision({ request, approve: true }); setReason(""); }}><Check size={14} /> Approve</Button>
                          <Button size="sm" variant="ghost" onClick={() => { setDecision({ request, approve: false }); setReason(""); }}><X size={14} /></Button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
                {!requests.length && <tr><td colSpan={7} className="table-empty">No access requests yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "classifications" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Data classification</h2><p>Automatic PII detection plus dataset-level labels. Restricted data requires an explicit grant.</p></div><Badge tone="danger">{classifications?.summary.pii_columns || 0} PII</Badge></div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Dataset</th><th>Column</th><th>Type</th><th>PII kind</th><th>Classification</th><th>Owner</th></tr></thead>
              <tbody>
                {classifications?.columns.map((column, index) => (
                  <tr key={`${column.dataset_id}-${column.column}-${index}`}>
                    <td><Link href={`/catalog/${column.dataset_id}`} className="mono-link">{column.dataset}</Link></td>
                    <td><code>{column.column}</code></td>
                    <td className="muted">{column.type}</td>
                    <td>{column.pii ? <Badge tone="danger">{column.pii_kind || "detected"}</Badge> : "—"}</td>
                    <td><Badge tone={classificationTone(column.classification)}>{column.classification}</Badge></td>
                    <td className="muted">{column.owner}</td>
                  </tr>
                ))}
                {!classifications?.columns.length && <tr><td colSpan={6} className="table-empty">No sensitive columns detected.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "audit" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Append-only audit log</h2><p>Hash-chained events. Each entry cites the request ID that produced it.</p></div><Button size="sm" variant="secondary" onClick={() => void load()}><RefreshCw size={14} /> Refresh</Button></div>
          <div className="audit-list">
            {audit.map((event) => (
              <div className="audit-row" key={event.id}>
                <div className="audit-seq">#{event.seq}</div>
                <div className="audit-main">
                  <div><strong>{event.action}</strong><Badge tone={event.outcome === "success" ? "success" : "danger"}>{event.outcome}</Badge></div>
                  <p>{event.actor_email} → {event.resource_type} <code>{event.resource_id.slice(0, 18)}</code></p>
                  <span className="audit-meta">{dateTime(event.created_at)} · request <code>{event.request_id}</code> · ip {event.ip || "internal"}</span>
                </div>
                <code className="audit-hash" title={event.hash}>{event.hash.slice(0, 12)}…</code>
              </div>
            ))}
            {!audit.length && <EmptyState title="No audit events" description="Mutations and data reads will appear here." />}
          </div>
        </section>
      )}

      {tab === "soc2" && soc2 && (
        <div className="soc2-layout">
          <section className="panel soc2-summary">
            <div className="soc2-seal"><ShieldCheck size={30} /></div>
            <h2>{soc2.framework}</h2>
            <p>Control mapping is generated from live configuration and audit evidence. Certification is an external audit outcome, not a product claim.</p>
            <div className="soc2-facts">
              <div><span>Audit events</span><strong>{soc2.latest_audit_seq}</strong></div>
              <div><span>Chain</span><strong>{soc2.audit_chain.valid ? "valid" : "broken"}</strong></div>
              <div><span>Open requests</span><strong>{soc2.open_access_requests}</strong></div>
            </div>
            <div className="retention"><strong>Retention</strong>{Object.entries(soc2.retention).map(([key, value]) => <span key={key}>{key}: {value}</span>)}</div>
            <Button variant="secondary" onClick={() => void verify()}><Fingerprint size={15} /> Verify evidence</Button>
          </section>
          <section className="panel">
            <div className="panel-head"><div><h2>Control evidence</h2><p>What the reference product actually enforces.</p></div><Badge tone="info">{soc2.controls.length} controls</Badge></div>
            <div className="control-list">
              {soc2.controls.map((control) => (
                <div className="control-row" key={control.id}>
                  <div className={`control-status ${control.status === "configured" ? "ok" : "partial"}`}>{control.status === "configured" ? <Check size={14} /> : "~"}</div>
                  <div><div className="control-title"><span>{control.id}</span><strong>{control.name}</strong></div><p>{control.evidence}</p></div>
                  <Badge tone={control.status === "configured" ? "success" : "warning"}>{control.status.replace("_", " ")}</Badge>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      <div className="governance-links">
        <Link href="/security">Manage users and API keys <ArrowUpRight size={14} /></Link>
        <Link href="/catalog">Review data catalog <ArrowUpRight size={14} /></Link>
      </div>

      <Modal open={!!decision} onClose={() => setDecision(null)} title={decision?.approve ? "Approve data access" : "Deny data access"} subtitle={decision ? `${decision.request.requester_email} · ${decision.request.dataset?.name || decision.request.dataset_id}` : ""} width="md"
        footer={<><Button variant="ghost" onClick={() => setDecision(null)}>Cancel</Button><Button variant={decision?.approve ? "primary" : "danger"} onClick={() => void decide()} disabled={busy}>{busy ? "Saving…" : decision?.approve ? "Approve & provision" : "Deny request"}</Button></>}>
        <div className="form-grid">
          <div className="review-box"><div><span>Action</span><strong>{decision?.request.action}</strong></div><div><span>Duration</span><strong>{decision?.request.duration_days} days</strong></div><div><span>Purpose</span><strong>{decision?.request.purpose}</strong></div></div>
          <Field label="Decision reason" hint="Recorded in the audit chain and shown to the requester.">
            <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Approved for the churn analysis; PII stays in the governed workspace." />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
