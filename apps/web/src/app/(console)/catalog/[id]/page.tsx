"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Braces, Copy, Database, FileSearch, GitBranch, Lock, Play, ShieldCheck, Sparkles, Table2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { bytes, classificationTone, dateTime, number } from "@/lib/format";
import type { Dataset, QueryResult } from "@/lib/types";
import { Badge, Button, EmptyState, InlineError, Spinner } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

type Tab = "preview" | "schema" | "profile" | "lineage" | "query";

export default function DatasetDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const toast = useToast();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [preview, setPreview] = useState<{ columns: string[]; rows: Array<Record<string, unknown>> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("preview");
  const [purpose, setPurpose] = useState("I need this data to answer a business question in the governed workspace.");
  const [requesting, setRequesting] = useState(false);
  const [sql, setSql] = useState("SELECT * FROM input LIMIT 50");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [querying, setQuerying] = useState(false);

  async function load() {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const detail = await api.get<Dataset>(`/datasets/${id}`);
      setDataset(detail);
      if (detail.can_read) {
        const rows = await api.get<{ columns: string[]; rows: Array<Record<string, unknown>> }>(`/datasets/${id}/preview?limit=50`);
        setPreview(rows);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  async function requestAccess() {
    if (!dataset) return;
    setRequesting(true);
    try {
      await api.post("/governance/access-requests", { dataset_id: dataset.id, action: "read", purpose, duration_days: 14 });
      toast.push("Access request submitted for steward review.", "success");
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setRequesting(false);
    }
  }

  async function runQuery() {
    if (!dataset) return;
    setQuerying(true);
    try {
      setQueryResult(await api.post<QueryResult>(`/datasets/${dataset.id}/query`, { dataset_id: dataset.id, sql, limit: 100 }));
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setQuerying(false);
    }
  }

  const profile = useMemo(() => (dataset?.profile?.columns || {}) as Record<string, { null_pct: number; distinct_sample: number; min?: number; max?: number }>, [dataset]);

  if (loading) return <Spinner label="Loading dataset" />;
  if (error) return <InlineError message={error} />;
  if (!dataset) return <InlineError message="Dataset not found." />;

  return (
    <div className="page-stack">
      <div className="run-back"><Link href="/catalog" className="back-link"><ArrowLeft size={15} /> Catalog</Link><ArrowRight size={13} /><span>{dataset.name}</span></div>

      <div className="dataset-header">
        <div className="dataset-heading">
          <div className="dataset-title-row">
            <span className={`layer-badge layer-${dataset.layer}`}>{dataset.layer}</span>
            <Badge tone={classificationTone(dataset.classification)}><ShieldCheck size={12} /> {dataset.classification}</Badge>
            <Badge tone="neutral">v{dataset.version}</Badge>
          </div>
          <h1>{dataset.name}</h1>
          <p>{dataset.description || "No business description yet."}</p>
          <div className="dataset-owner">Owner <strong>{dataset.owner || "unassigned"}</strong> · updated {dateTime(dataset.updated_at)} · source <code>{dataset.source_uri || "—"}</code></div>
        </div>
        <div className="dataset-actions">
          {dataset.can_read ? (
            <Link href={`/assistant?dataset=${dataset.id}`}><Button variant="secondary"><Sparkles size={15} /> Ask about this data</Button></Link>
          ) : (
            <Badge tone="danger"><Lock size={12} /> access restricted</Badge>
          )}
          <a href={`${api.baseUrl}/api/v1/datasets/${dataset.id}/download`} onClick={(event) => { event.preventDefault(); toast.push("Use the CLI or API to download with your bearer token.", "info"); }}><Button variant="ghost">Download</Button></a>
        </div>
      </div>

      <div className="run-facts">
        <div><span>Rows</span><strong>{number(dataset.row_count)}</strong></div>
        <div><span>Size</span><strong>{bytes(dataset.size_bytes)}</strong></div>
        <div><span>Columns</span><strong>{dataset.schema?.length || 0}</strong></div>
        <div><span>PII columns</span><strong>{dataset.schema?.filter((column) => column.pii).length || 0}</strong></div>
        <div><span>Format</span><strong>{dataset.format}</strong></div>
        <div><span>Lineage</span><strong>{dataset.lineage?.edges.length || 0} edges</strong></div>
      </div>

      {!dataset.can_read && (
        <div className="access-gate">
          <div className="access-gate-icon"><Lock size={22} /></div>
          <div>
            <h3>This dataset is restricted</h3>
            <p>Metadata is visible, but rows require an approved, expiring grant. Every read is audited.</p>
            <textarea rows={2} value={purpose} onChange={(event) => setPurpose(event.target.value)} />
          </div>
          <Button variant="primary" onClick={() => void requestAccess()} disabled={requesting}>{requesting ? "Submitting…" : "Request access"}</Button>
        </div>
      )}

      <div className="tabs">
        {([
          ["preview", "Preview", Table2],
          ["schema", "Schema", Braces],
          ["profile", "Profile", FileSearch],
          ["lineage", "Lineage", GitBranch],
          ["query", "Query", Play],
        ] as Array<[Tab, string, any]>).map(([value, label, Icon]) => (
          <button key={value} className={`tab ${tab === value ? "active" : ""}`} onClick={() => setTab(value)}><Icon size={14} /> {label}</button>
        ))}
      </div>

      {tab === "preview" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Row preview</h2><p>First 50 records from the current immutable version.</p></div><code className="request-code">{dataset.id}</code></div>
          {dataset.can_read && preview ? (
            <PreviewTable columns={preview.columns} rows={preview.rows} />
          ) : (
            <EmptyState icon={<Lock size={22} />} title="Preview requires a grant" description="Submit an access request above. Stewards can approve from Governance." />
          )}
        </section>
      )}

      {tab === "schema" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Schema</h2><p>Inferred types with automatic PII detection and classification.</p></div></div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Column</th><th>Type</th><th>Nullable</th><th>PII</th><th>Classification</th><th>Description</th></tr></thead>
              <tbody>
                {(dataset.schema || []).map((column) => (
                  <tr key={column.name}>
                    <td><code>{column.name}</code></td>
                    <td><span className="type-tag">{column.type}</span></td>
                    <td className="muted">{column.nullable ? "yes" : "no"}</td>
                    <td>{column.pii ? <Badge tone="danger">{column.pii_kind || "PII"}</Badge> : <span className="muted">—</span>}</td>
                    <td><Badge tone={classificationTone(column.classification)}>{column.classification}</Badge></td>
                    <td className="muted">{column.description || "No description."}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "profile" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Column profile</h2><p>Sampled statistics from the last ingestion. Null rates drive quality gates.</p></div></div>
          <div className="profile-grid">
            {(dataset.schema || []).map((column) => {
              const stats = profile[column.name] || { null_pct: 0, distinct_sample: 0 };
              return (
                <div className="profile-card" key={column.name}>
                  <div className="profile-head"><code>{column.name}</code><span>{stats.null_pct?.toFixed?.(1) || 0}% null</span></div>
                  <div className="null-track"><span style={{ width: `${Math.min(100, stats.null_pct || 0)}%` }} /></div>
                  <div className="profile-meta"><span>{stats.distinct_sample || 0} distinct</span>{stats.min !== undefined && <span>{String(stats.min)} → {String(stats.max)}</span>}</div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {tab === "lineage" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Lineage</h2><p>Dataset-level provenance from the platform lineage graph.</p></div><Link href={`/pipelines`} className="text-link">Open pipelines <ArrowRight size={13} /></Link></div>
          <div className="lineage-list">
            {(dataset.lineage?.edges || []).map((edge) => {
              const source = dataset.lineage?.nodes.find((node) => node.id === edge.source);
              const target = dataset.lineage?.nodes.find((node) => node.id === edge.target);
              return (
                <div className="lineage-row" key={edge.id}>
                  <div className="lineage-node"><span className={`layer-dot layer-${source?.layer || "raw"}`} /><strong>{source?.name || edge.source}</strong><small>{source?.layer}</small></div>
                  <div className="lineage-op"><span>{edge.operation}</span><ArrowRight size={14} /></div>
                  <div className="lineage-node"><span className={`layer-dot layer-${target?.layer || "raw"}`} /><strong>{target?.name || edge.target}</strong><small>{target?.layer}</small></div>
                </div>
              );
            })}
            {!dataset.lineage?.edges.length && <EmptyState icon={<GitBranch size={22} />} title="No lineage yet" description="Run a pipeline that reads or writes this dataset to register edges." />}
          </div>
        </section>
      )}

      {tab === "query" && (
        <section className="panel query-panel">
          <div className="panel-head"><div><h2>SQL workspace</h2><p>Read-only DuckDB over this dataset. The table is exposed as <code>input</code>.</p></div><Badge tone="warning">audited</Badge></div>
          <textarea className="query-editor" rows={7} value={sql} onChange={(event) => setSql(event.target.value)} />
          <div className="query-actions"><span className="muted">Only SELECT / WITH statements are accepted. External file access is disabled.</span><Button variant="dark" onClick={() => void runQuery()} disabled={querying || !dataset.can_read}>{querying ? "Running…" : "Run query"} <Play size={14} /></Button></div>
          {queryResult ? <PreviewTable columns={queryResult.columns} rows={queryResult.rows} /> : <div className="query-empty"><Database size={20} /><span>Run a query to preview governed results.</span></div>}
        </section>
      )}

      <div className="request-footer">Dataset {dataset.id} · <Copy size={12} /> lineage and profile update on every ingestion version.</div>
    </div>
  );
}

function PreviewTable({ columns, rows }: { columns: string[]; rows: Array<Record<string, unknown>> }) {
  if (!columns.length) return <EmptyState title="No rows" description="This version has no records." />;
  return (
    <div className="table-wrap preview-table">
      <table className="data-table">
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="table-empty">No rows returned.</div>}
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
