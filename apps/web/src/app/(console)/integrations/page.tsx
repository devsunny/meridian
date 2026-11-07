"use client";

import { useEffect, useState } from "react";
import { Boxes, Cable, CheckCircle2, Plus, RefreshCw, Settings2, Trash2, XCircle, Zap } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Integration } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

const TYPES = [
  { value: "airflow", label: "Apache Airflow", description: "Trigger a DAG run via the stable REST API." },
  { value: "dbt_cloud", label: "dbt Cloud", description: "Run a dbt job and record the provider response." },
  { value: "fivetran", label: "Fivetran", description: "Trigger a connector sync." },
  { value: "airbyte", label: "Airbyte", description: "Trigger an Airbyte connection sync." },
  { value: "webhook", label: "Generic webhook", description: "POST a Meridian run envelope to any HTTPS endpoint." },
];

export default function IntegrationsPage() {
  const toast = useToast();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("airflow");
  const [baseUrl, setBaseUrl] = useState("https://");
  const [secretRef, setSecretRef] = useState("");
  const [config, setConfig] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setIntegrations(await api.get<Integration[]>("/integrations"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      let parsed: Record<string, unknown> = {};
      try { parsed = JSON.parse(config || "{}"); } catch { throw new Error("Config must be valid JSON."); }
      await api.post("/integrations", { name, type, base_url: baseUrl, secret_ref: secretRef || null, config: parsed, enabled: true });
      setOpen(false);
      toast.push("Integration saved.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function test(integration: Integration) {
    setTesting(integration.id);
    try {
      const result = await api.post<{ ok: boolean; message: string }>(`/integrations/${integration.id}/test`);
      toast.push(result.message, result.ok ? "success" : "error");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setTesting(null);
    }
  }

  async function toggle(integration: Integration) {
    try {
      await api.patch(`/integrations/${integration.id}`, { enabled: !integration.enabled });
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  async function remove(integration: Integration) {
    if (!window.confirm(`Delete integration “${integration.name}”?`)) return;
    try {
      await api.delete(`/integrations/${integration.id}`);
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Ecosystem"
        title="Third-party ETL"
        description="Keep existing investments. Trigger Airflow DAGs, dbt Cloud jobs, Fivetran syncs, Airbyte connections or any webhook as DAG tasks."
        actions={<><Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /></Button><Button variant="primary" onClick={() => { setName(""); setType("airflow"); setBaseUrl("https://"); setSecretRef(""); setConfig("{\n  \"dag_id\": \"\"\n}"); setOpen(true); }}><Plus size={16} /> Add integration</Button></>}
      />
      {error && <InlineError message={error} />}

      <div className="integration-banner">
        <Zap size={20} />
        <div><strong>Outbound-only integration model</strong><span>The worker calls your ETL control plane with a secret from the secret manager and propagates the run request ID in X-Request-ID.</span></div>
        <Badge tone="info">etl.trigger task</Badge>
      </div>

      {loading ? <Spinner label="Loading integrations" /> : integrations.length === 0 ? (
        <EmptyState icon={<Cable size={24} />} title="No ETL integrations" description="Connect Airflow, dbt Cloud, Fivetran, Airbyte or a generic webhook." action={<Button variant="primary" onClick={() => setOpen(true)}><Plus size={16} /> Add integration</Button>} />
      ) : (
        <div className="cards-grid">
          {integrations.map((integration) => (
            <article className="integration-card" key={integration.id}>
              <div className="integration-head">
                <div className="integration-icon"><Boxes size={19} /></div>
                <div><h3>{integration.name}</h3><span>{TYPES.find((item) => item.value === integration.type)?.label || integration.type}</span></div>
                <Badge tone={integration.enabled ? "success" : "neutral"} dot>{integration.enabled ? "enabled" : "disabled"}</Badge>
              </div>
              <div className="integration-url">{integration.base_url}</div>
              <div className="integration-meta">
                <span>Secret <strong>{integration.has_secret ? "configured" : "none"}</strong></span>
                <span>Tested <strong>{integration.last_tested_at ? dateTime(integration.last_tested_at) : "never"}</strong></span>
              </div>
              {integration.status === "unreachable" && <div className="source-warning"><XCircle size={14} /> Last test failed</div>}
              {integration.status === "healthy" && <div className="source-ok"><CheckCircle2 size={14} /> Provider reachable</div>}
              <div className="integration-actions">
                <Button size="sm" variant="secondary" onClick={() => void test(integration)} disabled={testing === integration.id}>{testing === integration.id ? "Testing…" : "Test"}</Button>
                <Button size="sm" variant="ghost" onClick={() => void toggle(integration)}>{integration.enabled ? "Disable" : "Enable"}</Button>
                <Button size="sm" variant="ghost" onClick={() => void remove(integration)}><Trash2 size={14} /></Button>
              </div>
            </article>
          ))}
        </div>
      )}

      <div className="integration-detail-grid">
        <div className="panel"><div className="panel-head"><div><h2>Provider contract</h2><p>What the worker sends when the task fires.</p></div><Settings2 size={17} className="panel-icon" /></div>
          <div className="provider-table">
            <div><strong>Airflow</strong><code>POST /api/v1/dags/{"{dag_id}"}/dagRuns</code></div>
            <div><strong>dbt Cloud</strong><code>POST /api/v2/accounts/{"{account}"}/jobs/{"{job}"}/run/</code></div>
            <div><strong>Fivetran</strong><code>POST /v1/connectors/{"{connector}"}/sync</code></div>
            <div><strong>Airbyte</strong><code>POST /api/v1/connections/sync</code></div>
            <div><strong>Webhook</strong><code>POST {"{base_url}"}</code></div>
          </div>
        </div>
        <div className="panel"><div className="panel-head"><div><h2>Credential handling</h2><p>No tokens in Git or the database.</p></div></div><ul className="clean-list"><li>Store the token in AWS Secrets Manager or the environment.</li><li>Reference it as <code>env:NAME</code> or <code>aws-sm:ARN</code>.</li><li>The worker resolves it only at execution time.</li><li>Provider responses are truncated and never logged with the token.</li></ul></div>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Add ETL integration" subtitle="Credentials are referenced, not stored. The worker calls the provider at task execution time." width="lg"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="integration-form" disabled={saving}>{saving ? "Saving…" : "Save integration"}</Button></>}>
        <form id="integration-form" onSubmit={create} className="form-grid">
          <div className="form-grid two">
            <Field label="Name" required><input value={name} onChange={(event) => setName(event.target.value)} required placeholder="Airflow production" /></Field>
            <Field label="Provider"><select value={type} onChange={(event) => {
              const value = event.target.value;
              setType(value);
              setConfig(value === "airflow" ? "{\n  \"dag_id\": \"\"\n}" : value === "dbt_cloud" ? "{\n  \"account_id\": \"\",\n  \"job_id\": \"\"\n}" : value === "fivetran" ? "{\n  \"connector_id\": \"\"\n}" : value === "airbyte" ? "{\n  \"connection_id\": \"\"\n}" : "{}");
            }}>{TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
          </div>
          <Field label="Base URL" required><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://airflow.example.com" required /></Field>
          <Field label="Secret reference" hint="env:AIRFLOW_TOKEN or aws-sm:arn"><input value={secretRef} onChange={(event) => setSecretRef(event.target.value)} placeholder="env:AIRFLOW_TOKEN" /></Field>
          <Field label="Provider config (JSON)" hint="dag_id, account_id/job_id, connector_id or connection_id."><textarea className="code-input" rows={5} value={config} onChange={(event) => setConfig(event.target.value)} /></Field>
          <div className="connector-callout"><div><Cable size={17} /></div><p><strong>{TYPES.find((item) => item.value === type)?.label}.</strong> {TYPES.find((item) => item.value === type)?.description}</p></div>
        </form>
      </Modal>
    </div>
  );
}
