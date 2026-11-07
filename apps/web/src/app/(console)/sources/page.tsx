"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  Cloud,
  Database,
  FileUp,
  Folder,
  Globe,
  HardDrive,
  Plus,
  RefreshCw,
  Search,
  Server,
  SlidersHorizontal,
  XCircle,
} from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { dateTime, relativeTime, titleCase } from "@/lib/format";
import type { Connection, Connector, Resource } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

const ICONS: Record<string, React.ReactNode> = {
  folder: <Folder size={19} />,
  globe: <Globe size={19} />,
  database: <Database size={19} />,
  cloud: <Cloud size={19} />,
  server: <Server size={19} />,
  "hard-drive": <HardDrive size={19} />,
  box: <Database size={19} />,
  plug: <SlidersHorizontal size={19} />,
};

export default function SourcesPage() {
  const router = useRouter();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedType, setSelectedType] = useState("file");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [discover, setDiscover] = useState<{ connection: Connection; resources: Resource[] } | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [rows, catalog] = await Promise.all([api.get<Connection[]>("/connections"), api.get<Connector[]>("/connectors")]);
      setConnections(rows);
      setConnectors(catalog);
      if (!catalog.find((item) => item.type === selectedType) && catalog.length) setSelectedType(catalog[0].type);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const connector = useMemo(() => connectors.find((item) => item.type === selectedType), [connectors, selectedType]);
  const connectorMap = useMemo(() => Object.fromEntries(connectors.map((item) => [item.type, item])), [connectors]);

  function openCreate(type = "file") {
    const chosen = connectors.find((item) => item.type === type) || connectors[0];
    setSelectedType(chosen?.type || "file");
    setName("");
    setDescription("");
    const initial: Record<string, unknown> = {};
    chosen?.config_schema.forEach((field) => {
      if (field.default !== null && field.default !== undefined && field.default !== "") initial[field.name] = field.default;
    });
    setConfig(initial);
    setCreateOpen(true);
  }

  function switchType(type: string) {
    const chosen = connectors.find((item) => item.type === type);
    setSelectedType(type);
    const initial: Record<string, unknown> = {};
    chosen?.config_schema.forEach((field) => {
      if (field.default !== null && field.default !== undefined && field.default !== "") initial[field.name] = field.default;
    });
    setConfig(initial);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const cleaned: Record<string, unknown> = {};
      connector?.config_schema.forEach((field) => {
        const value = config[field.name];
        if (value === undefined || value === "") return;
        if (field.type === "integer") cleaned[field.name] = Number(value);
        else if (field.type === "boolean") cleaned[field.name] = value === true || value === "true";
        else cleaned[field.name] = value;
      });
      await api.post<Connection>("/connections", {
        name,
        type: selectedType,
        description,
        config: cleaned,
      });
      setCreateOpen(false);
      toast.push("Source created. Run a connection test next.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function testConnection(connection: Connection) {
    setTestingId(connection.id);
    try {
      const result = await api.post<{ ok: boolean; message: string }>(`/connections/${connection.id}/test`);
      toast.push(result.message, result.ok ? "success" : "error");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setTestingId(null);
    }
  }

  async function discoverConnection(connection: Connection) {
    try {
      const payload = await api.post<{ resources: Resource[] }>(`/connections/${connection.id}/discover`);
      setDiscover({ connection, resources: payload.resources });
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  async function upload(file: File) {
    setUploading(true);
    try {
      const result = await api.upload<{ connection: Connection }>("/uploads", file);
      toast.push(`Uploaded ${file.name}. Source is ready to ingest.`, "success");
      await load();
      router.push(`/ingestions?connection=${result.connection.id}`);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const filtered = connections.filter((connection) =>
    `${connection.name} ${connection.type} ${connection.owner}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Connectivity"
        title="Sources"
        description="Connect databases, files, object stores and SaaS content. Credentials live in a secret manager, never in the metadata store."
        actions={
          <>
            <input ref={fileInput} type="file" hidden onChange={(event) => event.target.files?.[0] && void upload(event.target.files[0])} />
            <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={uploading}>
              <FileUp size={16} /> {uploading ? "Uploading…" : "Upload file"}
            </Button>
            <Button variant="primary" onClick={() => openCreate()}><Plus size={16} /> New source</Button>
          </>
        }
      />

      <div className="connector-strip">
        {connectors.slice(0, 7).map((item) => (
          <button key={item.type} className="connector-chip" onClick={() => openCreate(item.type)}>
            <span className="connector-chip-icon">{ICONS[item.icon] || <Database size={17} />}</span>
            <span><strong>{item.label}</strong><small>{item.category}</small></span>
          </button>
        ))}
      </div>

      {error && <InlineError message={error} />}

      <div className="toolbar">
        <div className="search-field">
          <Search size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter sources by name or type…" />
        </div>
        <div className="toolbar-meta">{filtered.length} source{filtered.length === 1 ? "" : "s"}</div>
        <Button variant="ghost" onClick={() => void load()}><RefreshCw size={15} /></Button>
      </div>

      {loading ? (
        <Spinner label="Loading sources" />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Database size={24} />}
          title="No sources yet"
          description="Start with a CSV upload or connect a database, S3 bucket, SFTP server or SaaS drive."
          action={<Button variant="primary" onClick={() => openCreate()}><Plus size={16} /> Connect your first source</Button>}
        />
      ) : (
        <div className="cards-grid">
          {filtered.map((connection) => {
            const meta = connectorMap[connection.type];
            return (
              <article className="source-card" key={connection.id}>
                <div className="source-card-head">
                  <div className="source-icon">{ICONS[meta?.icon || "plug"] || <Database size={19} />}</div>
                  <div className="source-title">
                    <h3>{connection.name}</h3>
                    <span>{meta?.label || titleCase(connection.type)}</span>
                  </div>
                  <StatusBadge status={connection.status} />
                </div>
                <p className="source-description">{connection.description || "No description."}</p>
                <div className="source-meta">
                  <span>Owner <strong>{connection.owner || "—"}</strong></span>
                  <span>Tested <strong>{connection.last_tested_at ? relativeTime(connection.last_tested_at) : "never"}</strong></span>
                </div>
                {connection.last_test_ok === false && (
                  <div className="source-warning"><XCircle size={14} /> Last connection test failed</div>
                )}
                {connection.last_test_ok === true && (
                  <div className="source-ok"><CheckCircle2 size={14} /> Connection verified {dateTime(connection.last_tested_at)}</div>
                )}
                <div className="source-actions">
                  <Button size="sm" variant="secondary" onClick={() => void testConnection(connection)} disabled={testingId === connection.id}>
                    {testingId === connection.id ? "Testing…" : "Test"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void discoverConnection(connection)}>Discover</Button>
                  <Button size="sm" variant="ghost" onClick={() => router.push(`/ingestions?connection=${connection.id}`)}>Ingest →</Button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Connect a source"
        subtitle="Secrets are referenced, not stored. Use env:NAME, aws-sm:ARN or file:/mounted/path."
        width="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="source-form" disabled={saving}>{saving ? "Creating…" : "Create source"}</Button>
          </>
        }
      >
        <form id="source-form" onSubmit={submit} className="form-grid">
          <Field label="Connector type" required>
            <select value={selectedType} onChange={(event) => switchType(event.target.value)}>
              {connectors.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}
            </select>
          </Field>
          <Field label="Display name" required>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Sales orders — production" required minLength={2} />
          </Field>
          <Field label="Description" hint="What business data lives here? This appears in the catalog.">
            <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Daily commerce export from the ERP" />
          </Field>
          {connector && (
            <div className="connector-callout">
              <div>{ICONS[connector.icon] || <Database size={17} />}</div>
              <p><strong>{connector.label}.</strong> {connector.description}</p>
            </div>
          )}
          <div className="form-divider">Connection settings</div>
          <div className="form-grid two">
            {connector?.config_schema.map((field) => {
              const value = config[field.name];
              if (field.type === "boolean") {
                return (
                  <Field key={field.name} label={field.label} hint={field.help}>
                    <select value={String(value ?? field.default ?? false)} onChange={(event) => setConfig({ ...config, [field.name]: event.target.value === "true" })}>
                      <option value="true">Enabled</option>
                      <option value="false">Disabled</option>
                    </select>
                  </Field>
                );
              }
              if (field.type === "select") {
                return (
                  <Field key={field.name} label={field.label} hint={field.help} required={field.required}>
                    <select value={String(value ?? field.default ?? "")} onChange={(event) => setConfig({ ...config, [field.name]: event.target.value })}>
                      {field.options.map((option) => <option key={option}>{option}</option>)}
                    </select>
                  </Field>
                );
              }
              if (field.type === "textarea") {
                return (
                  <Field key={field.name} label={field.label} hint={field.help} required={field.required}>
                    <textarea rows={3} value={String(value ?? "")} onChange={(event) => setConfig({ ...config, [field.name]: event.target.value })} placeholder={field.help} />
                  </Field>
                );
              }
              return (
                <Field key={field.name} label={field.label} hint={field.help} required={field.required}>
                  <input
                    type={field.type === "integer" ? "number" : "text"}
                    value={String(value ?? "")}
                    onChange={(event) => setConfig({ ...config, [field.name]: event.target.value })}
                    placeholder={field.type === "secret" ? "env:MY_SECRET" : field.help}
                  />
                </Field>
              );
            })}
          </div>
        </form>
      </Modal>

      <Modal
        open={!!discover}
        onClose={() => setDiscover(null)}
        title={`Discovered resources · ${discover?.connection.name || ""}`}
        subtitle="Select a resource when you create an ingestion. File sizes and schema hints come from the connector."
        width="lg"
        footer={<Button variant="primary" onClick={() => {
          if (discover) router.push(`/ingestions?connection=${discover.connection.id}`);
          setDiscover(null);
        }}>Create ingestion from this source</Button>}
      >
        <div className="resource-list">
          {discover?.resources.map((resource) => (
            <div className="resource-row" key={resource.id}>
              <div className="resource-icon">{resource.kind === "table" ? <Database size={16} /> : <Folder size={16} />}</div>
              <div><strong>{resource.name}</strong><small>{resource.path || resource.id}</small></div>
              <span>{resource.kind}</span>
              <span>{resource.size ? `${(resource.size / 1024).toFixed(1)} KB` : "—"}</span>
            </div>
          ))}
          {!discover?.resources.length && <EmptyState title="No resources found" description="Check the path, permissions or query filters." />}
        </div>
      </Modal>
    </div>
  );
}
