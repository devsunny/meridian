"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDownToLine, ArrowRight, CalendarClock, Check, Database, FileText, Loader2, Play, Plus, RefreshCw, Search, Wand2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { cronSummary, dateTime, relativeTime, titleCase } from "@/lib/format";
import type { Connection, Connector, Ingestion, Resource } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

const STEPS = ["Source", "Resource", "Destination", "Schedule"];

export default function IngestionsPage() {
  const router = useRouter();
  const toast = useToast();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [ingestions, setIngestions] = useState<Ingestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [connectionId, setConnectionId] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const [resourceId, setResourceId] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [description, setDescription] = useState("");
  const [layer, setLayer] = useState("bronze");
  const [classification, setClassification] = useState("auto");
  const [cron, setCron] = useState("");
  const [timezone, setTimezone] = useState("America/New_York");
  const [runNow, setRunNow] = useState(true);
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [connectionRows, catalog, ingestionRows] = await Promise.all([
        api.get<Connection[]>("/connections"),
        api.get<Connector[]>("/connectors"),
        api.get<Ingestion[]>("/ingestions"),
      ]);
      setConnections(connectionRows.filter((item) => item.status === "active"));
      setConnectors(catalog);
      setIngestions(ingestionRows);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const params = new URLSearchParams(window.location.search);
    const preselected = params.get("connection");
    if (preselected) {
      setConnectionId(preselected);
      setWizardOpen(true);
      setStep(1);
      void discover(preselected);
    }
  }, []);

  const connectionMap = useMemo(() => Object.fromEntries(connections.map((item) => [item.id, item])), [connections]);
  const connectorMap = useMemo(() => Object.fromEntries(connectors.map((item) => [item.type, item])), [connectors]);

  function openWizard() {
    setStep(0);
    setConnectionId(connections[0]?.id || "");
    setResources([]);
    setResourceId("");
    setName("");
    setTarget("");
    setDescription("");
    setLayer("bronze");
    setClassification("auto");
    setCron("");
    setTimezone("America/New_York");
    setRunNow(true);
    setWizardOpen(true);
  }

  async function discover(id = connectionId) {
    if (!id) return;
    setDiscovering(true);
    setResources([]);
    setResourceId("");
    try {
      const payload = await api.post<{ resources: Resource[] }>(`/connections/${id}/discover`);
      setResources(payload.resources);
      if (payload.resources.length) setResourceId(payload.resources[0].id);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setDiscovering(false);
    }
  }

  function chooseConnection(id: string) {
    setConnectionId(id);
    setResources([]);
    setResourceId("");
    setStep(1);
    void discover(id);
  }

  async function create() {
    if (!connectionId || !resourceId || !name || !target) {
      toast.push("Complete source, resource, name and target dataset.", "error");
      return;
    }
    setSaving(true);
    try {
      const ingestion = await api.post<Ingestion>("/ingestions", {
        name,
        description,
        connection_id: connectionId,
        target_dataset: target,
        spec: { resource: resourceId, layer, classification, options: { max_bytes: 104857600 } },
        schedule_cron: cron || null,
        schedule_timezone: timezone,
        owner: "",
      });
      if (runNow) {
        await api.post(`/ingestions/${ingestion.id}/run`, { force: false });
      }
      setWizardOpen(false);
      toast.push(runNow ? "Ingestion created and queued." : "Ingestion created.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function run(ingestion: Ingestion) {
    setRunningId(ingestion.id);
    try {
      const run = await api.post<{ id: string }>(`/ingestions/${ingestion.id}/run`, { force: false });
      toast.push("Run queued. Follow it in Runs & debug.", "success");
      router.push(`/runs/${run.id}`);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setRunningId(null);
    }
  }

  const filtered = ingestions.filter((item) =>
    `${item.name} ${item.target_dataset} ${connectionMap[item.connection_id]?.name || ""}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Data movement"
        title="Ingestion"
        description="Land relational, semi-structured and unstructured sources with schema inference, PII detection and an auditable run history."
        actions={
          <>
            <Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /></Button>
            <Button variant="primary" onClick={openWizard}><Plus size={16} /> New ingestion</Button>
          </>
        }
      />

      {error && <InlineError message={error} />}

      <div className="metric-strip">
        <div><span>Ingestions</span><strong>{ingestions.length}</strong></div>
        <div><span>Active</span><strong>{ingestions.filter((item) => item.status === "active").length}</strong></div>
        <div><span>Scheduled</span><strong>{ingestions.filter((item) => item.schedule_cron).length}</strong></div>
        <div><span>Sources</span><strong>{connections.length}</strong></div>
      </div>

      <div className="toolbar">
        <div className="search-field"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter ingestions…" /></div>
        <Button variant="ghost" onClick={openWizard}><Wand2 size={15} /> Wizard</Button>
      </div>

      {loading ? (
        <Spinner label="Loading ingestions" />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<ArrowDownToLine size={24} />}
          title="No ingestion definitions"
          description="Create a self-service ingestion: choose a source, discover a resource, map a target and schedule it."
          action={<Button variant="primary" onClick={openWizard}><Plus size={16} /> Create ingestion</Button>}
        />
      ) : (
        <div className="table-card">
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Ingestion</th><th>Source</th><th>Target dataset</th><th>Schedule</th><th>Last run</th><th>Status</th><th /></tr></thead>
              <tbody>
                {filtered.map((ingestion) => {
                  const connection = connectionMap[ingestion.connection_id];
                  const meta = connection ? connectorMap[connection.type] : undefined;
                  return (
                    <tr key={ingestion.id}>
                      <td>
                        <div className="cell-title">{ingestion.name}</div>
                        <div className="cell-sub">{ingestion.description || `${meta?.label || connection?.type || "source"} → ${ingestion.target_dataset}`}</div>
                      </td>
                      <td><span className="type-tag">{meta?.label || connection?.type || "—"}</span></td>
                      <td><code className="code-chip">{ingestion.target_dataset}</code></td>
                      <td>{ingestion.schedule_cron ? <span className="schedule-inline"><CalendarClock size={13} /> {cronSummary(ingestion.schedule_cron)}</span> : <span className="muted">On demand</span>}</td>
                      <td className="muted">{ingestion.last_run_at ? relativeTime(ingestion.last_run_at) : "Never"}</td>
                      <td><StatusBadge status={ingestion.status} /></td>
                      <td className="row-actions">
                        <Button size="sm" variant="ghost" onClick={() => void run(ingestion)} disabled={runningId === ingestion.id}>
                          {runningId === ingestion.id ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Run
                        </Button>
                        {ingestion.last_run_id && <Link className="text-link" href={`/runs/${ingestion.last_run_id}`}>Last run</Link>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        title="New ingestion"
        subtitle="Four steps: source, resource, destination and schedule. Everything is saved as a versioned definition."
        width="xl"
        footer={
          <>
            {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>}
            <div className="footer-spacer" />
            {step < 3 ? (
              <Button
                variant="primary"
                onClick={() => {
                  if (step === 0 && !connectionId) return toast.push("Choose a source.", "error");
                  if (step === 1 && !resourceId) return toast.push("Choose a resource.", "error");
                  setStep(step + 1);
                }}
              >
                Continue <ArrowRight size={15} />
              </Button>
            ) : (
              <Button variant="primary" onClick={() => void create()} disabled={saving}>{saving ? "Creating…" : runNow ? "Create & run" : "Create ingestion"}</Button>
            )}
          </>
        }
      >
        <div className="stepper">
          {STEPS.map((label, index) => (
            <div key={label} className={`step ${index === step ? "active" : ""} ${index < step ? "done" : ""}`}>
              <span>{index < step ? <Check size={13} /> : index + 1}</span>
              {label}
            </div>
          ))}
        </div>

        {step === 0 && (
          <div className="wizard-panel">
            <h3>Where does the data live?</h3>
            <p className="muted">Choose an existing connection. Credentials and network policy are attached to it.</p>
            <div className="source-picker">
              {connections.map((connection) => (
                <button key={connection.id} className={`picker-card ${connection.id === connectionId ? "selected" : ""}`} onClick={() => chooseConnection(connection.id)}>
                  <div className="picker-icon"><Database size={18} /></div>
                  <div><strong>{connection.name}</strong><span>{connectorMap[connection.type]?.label || titleCase(connection.type)} · {connection.status}</span></div>
                  {connection.id === connectionId && <Check size={16} />}
                </button>
              ))}
            </div>
            {!connections.length && <EmptyState icon={<Database size={22} />} title="No active sources" description="Create a source connection first." action={<Button onClick={() => router.push("/sources")}>Open sources</Button>} />}
          </div>
        )}

        {step === 1 && (
          <div className="wizard-panel">
            <h3>Choose a resource</h3>
            <p className="muted">{connectionMap[connectionId]?.name} · discovery reads metadata only; it does not copy payload bytes.</p>
            {discovering ? <Spinner label="Discovering resources" /> : (
              <div className="resource-picker">
                {resources.map((resource) => (
                  <button key={resource.id} className={`picker-card ${resource.id === resourceId ? "selected" : ""}`} onClick={() => setResourceId(resource.id)}>
                    <div className="picker-icon">{resource.kind === "table" || resource.kind === "collection" ? <Database size={18} /> : <FileText size={18} />}</div>
                    <div><strong>{resource.name}</strong><span>{resource.kind} · {resource.path || resource.id}</span></div>
                    {resource.id === resourceId && <Check size={16} />}
                  </button>
                ))}
                {!resources.length && <EmptyState title="No resources discovered" description="Check the source path or query configuration." />}
              </div>
            )}
            <Button variant="ghost" size="sm" onClick={() => void discover()}><RefreshCw size={14} /> Re-run discovery</Button>
          </div>
        )}

        {step === 2 && (
          <div className="wizard-panel form-grid">
            <h3>Destination and classification</h3>
            <p className="muted">The dataset name is a stable contract. Re-ingesting creates a new immutable version.</p>
            <Field label="Ingestion name" required>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Daily sales orders" />
            </Field>
            <Field label="Target dataset" hint="Lowercase letters, numbers and underscores." required>
              <input value={target} onChange={(event) => setTarget(event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} placeholder="sales_orders_raw" />
            </Field>
            <Field label="Description">
              <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What does this data mean?" />
            </Field>
            <div className="form-grid two">
              <Field label="Medallion layer">
                <select value={layer} onChange={(event) => setLayer(event.target.value)}>
                  <option value="raw">Raw</option><option value="bronze">Bronze</option><option value="silver">Silver</option><option value="gold">Gold</option>
                </select>
              </Field>
              <Field label="Classification" hint="Auto uses PII detection; restricted requires grants.">
                <select value={classification} onChange={(event) => setClassification(event.target.value)}>
                  <option value="auto">Auto-detect</option><option value="public">Public</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option>
                </select>
              </Field>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="wizard-panel form-grid">
            <h3>Schedule and run</h3>
            <p className="muted">Schedules are durable, timezone-aware and materialised exactly once per logical date.</p>
            <div className="form-grid two">
              <Field label="Cron expression" hint="Leave blank for on-demand only. Example: 0 2 * * *">
                <input value={cron} onChange={(event) => setCron(event.target.value)} placeholder="0 2 * * *" />
              </Field>
              <Field label="Timezone">
                <select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
                  <option>America/New_York</option><option>UTC</option><option>Europe/London</option><option>Asia/Tokyo</option><option>Asia/Kolkata</option>
                </select>
              </Field>
            </div>
            <label className="checkbox-row">
              <input type="checkbox" checked={runNow} onChange={(event) => setRunNow(event.target.checked)} />
              Run once immediately after creation
            </label>
            <div className="review-box">
              <div><span>Source</span><strong>{connectionMap[connectionId]?.name}</strong></div>
              <div><span>Resource</span><strong>{resources.find((item) => item.id === resourceId)?.name || "—"}</strong></div>
              <div><span>Target</span><strong>{target || "—"}</strong></div>
              <div><span>Schedule</span><strong>{cron ? cronSummary(cron) : "On demand"}</strong></div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
