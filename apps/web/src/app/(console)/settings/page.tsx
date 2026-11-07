"use client";

import { useEffect, useState } from "react";
import { Activity, Boxes, Braces, CheckCircle2, Cloud, Database, ExternalLink, GitBranch, Radio, Server, ShieldCheck, TerminalSquare } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Badge, InlineError, PageHeader, Spinner } from "@/components/ui";

interface Info {
  name: string;
  version: string;
  environment: string;
  service: string;
  request_id: string;
  auth_mode: string;
  storage_backend: string;
  otel_enabled: boolean;
  database: { ok: boolean; message: string };
  features: Record<string, boolean>;
  user: string;
}

export default function SettingsPage() {
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Info>("/system/info").then(setInfo).catch((err) => setError(errorMessage(err)));
  }, []);

  if (error) return <InlineError message={error} />;
  if (!info) return <Spinner label="Loading platform info" />;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Operations"
        title="Platform"
        description="Runtime configuration, enabled capabilities and the open-source architecture behind this deployment."
        actions={<a href={`${api.baseUrl}/docs`} target="_blank" rel="noreferrer"><button className="btn btn-secondary btn-md">OpenAPI docs <ExternalLink size={14} /></button></a>}
      />

      <div className="platform-hero">
        <div className="platform-logo"><span /><span /><span /><span /></div>
        <div>
          <h2>{info.name} <Badge tone="info">v{info.version}</Badge></h2>
          <p>{info.service} · {info.environment} · signed in as {info.user}</p>
        </div>
        <div className="platform-health"><CheckCircle2 size={16} /><span>API healthy</span><Badge tone={info.database.ok ? "success" : "danger"}>{info.database.ok ? "database ready" : "database down"}</Badge></div>
      </div>

      <div className="platform-grid">
        <section className="panel">
          <div className="panel-head"><div><h2>Runtime</h2><p>Effective configuration for this process.</p></div><Server size={18} className="panel-icon" /></div>
          <div className="kv-list">
            <div><span>API version</span><strong>{info.version}</strong></div>
            <div><span>Environment</span><strong>{info.environment}</strong></div>
            <div><span>Authentication</span><strong>{info.auth_mode === "oidc" ? "OIDC / SSO" : "Local JWT"}</strong></div>
            <div><span>Metadata store</span><strong>PostgreSQL-compatible</strong></div>
            <div><span>Object storage</span><strong>{info.storage_backend}</strong></div>
            <div><span>Database</span><strong>{info.database.message}</strong></div>
            <div><span>OpenTelemetry</span><strong>{info.otel_enabled ? "OTLP enabled" : "disabled (local)"}</strong></div>
            <div><span>Request ID</span><code>{info.request_id}</code></div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><div><h2>Capabilities</h2><p>Wired into this build.</p></div><Boxes size={18} className="panel-icon" /></div>
          <div className="feature-grid">
            {Object.entries(info.features).map(([key, enabled]) => (
              <div key={key} className={enabled ? "feature-row" : "feature-row disabled"}>
                <span className="feature-dot" />
                <span>{key.replace(/_/g, " ")}</span>
                <Badge tone={enabled ? "success" : "neutral"}>{enabled ? "on" : "off"}</Badge>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="panel architecture-panel">
        <div className="panel-head"><div><h2>Reference architecture</h2><p>Stateless roles over a shared metadata store and leased task queue.</p></div><GitBranch size={18} className="panel-icon" /></div>
        <div className="arch-flow">
          <div className="arch-box"><TerminalSquare size={18} /><strong>Next.js console</strong><span>web · TypeScript</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-box accent"><Braces size={18} /><strong>FastAPI control plane</strong><span>api · Python</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-box"><Database size={18} /><strong>PostgreSQL</strong><span>metadata · queue · audit</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-box"><Activity size={18} /><strong>Worker pool</strong><span>leased tasks · SKIP LOCKED</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-box"><Cloud size={18} /><strong>Lake / sources</strong><span>S3 · files · SaaS · DB</span></div>
        </div>
        <div className="arch-notes">
          <span><Radio size={14} /> OTel traces + Prometheus metrics + JSONL logs</span>
          <span><ShieldCheck size={14} /> Tenant scoping and audit hash chain</span>
          <span><GitBranch size={14} /> Scheduler and workers scale horizontally</span>
        </div>
      </section>

      <div className="deploy-grid">
        <div className="panel"><div className="panel-head"><div><h2>Local</h2><p>Docker Compose profile</p></div></div><pre className="deploy-snippet">{`docker compose -f deploy/compose/app.yaml up --build
open http://localhost:3000`}</pre><p className="muted">API at :8000 · worker and scheduler containers included.</p></div>
        <div className="panel"><div className="panel-head"><div><h2>Kubernetes</h2><p>Kustomize + EKS</p></div></div><pre className="deploy-snippet">{`kubectl apply -k deploy/k8s
# HPA: api, worker
# PDB + NetworkPolicy + IRSA`}</pre><p className="muted">See <code>deploy/eks/README.md</code> for the EKS reference.</p></div>
        <div className="panel"><div className="panel-head"><div><h2>CLI</h2><p>Same public API</p></div></div><pre className="deploy-snippet">{`meridian login --url http://localhost:8000
meridian pipelines list
meridian ask "refund policy?"`}</pre><p className="muted">Machine access uses expiring keys or JWTs.</p></div>
      </div>

      <div className="request-footer">Platform request <code>{info.request_id}</code> · check /health/ready for probes.</div>
    </div>
  );
}
