"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BookOpen, Database, Filter, History, Search, ShieldCheck } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { bytes, classificationTone, dateTime, number, relativeTime } from "@/lib/format";
import type { Dataset } from "@/lib/types";
import { Badge, Button, EmptyState, InlineError, PageHeader, Spinner } from "@/components/ui";

export default function CatalogPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [layer, setLayer] = useState("");
  const [classification, setClassification] = useState("");
  const [stats, setStats] = useState<{ datasets: number; rows: number; bytes: number; pii_columns: number; by_layer: Record<string, number> } | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [rows, catalogStats] = await Promise.all([api.get<Dataset[]>("/datasets"), api.get<any>("/catalog/stats")]);
      setDatasets(rows);
      setStats(catalogStats);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) setQuery(q);
  }, []);

  const filtered = useMemo(
    () =>
      datasets.filter((dataset) => {
        if (layer && dataset.layer !== layer) return false;
        if (classification && dataset.classification !== classification) return false;
        if (query && !`${dataset.name} ${dataset.description} ${dataset.owner}`.toLowerCase().includes(query.toLowerCase())) return false;
        return true;
      }),
    [datasets, query, layer, classification],
  );

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Metadata"
        title="Data catalog"
        description="A governed index of every dataset, its schema, classification, lineage and owning team. Metadata is always visible; rows are grant-gated."
        actions={<Link href="/assistant"><Button variant="secondary"><BookOpen size={15} /> Ask the catalog</Button></Link>}
      />

      {error && <InlineError message={error} />}

      <div className="catalog-stats">
        <div><span>Datasets</span><strong>{stats?.datasets ?? datasets.length}</strong></div>
        <div><span>Rows indexed</span><strong>{number(stats?.rows)}</strong></div>
        <div><span>Stored bytes</span><strong>{bytes(stats?.bytes)}</strong></div>
        <div><span>PII columns</span><strong className="warn">{stats?.pii_columns ?? 0}</strong></div>
        <div className="catalog-layer-pills">
          {["raw", "bronze", "silver", "gold"].map((item) => <span key={item} className={`layer-pill layer-${item}`}>{item} · {stats?.by_layer?.[item] || 0}</span>)}
        </div>
      </div>

      <div className="toolbar">
        <div className="search-field"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name, owner or meaning…" /></div>
        <div className="filter-group">
          <Filter size={14} />
          <select value={layer} onChange={(event) => setLayer(event.target.value)}>
            <option value="">All layers</option><option value="raw">Raw</option><option value="bronze">Bronze</option><option value="silver">Silver</option><option value="gold">Gold</option>
          </select>
          <select value={classification} onChange={(event) => setClassification(event.target.value)}>
            <option value="">All classifications</option><option value="public">Public</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option>
          </select>
        </div>
      </div>

      {loading ? <Spinner label="Loading catalog" /> : filtered.length === 0 ? (
        <EmptyState icon={<Database size={24} />} title="No datasets match" description="Adjust the filters, or land a new source through ingestion." />
      ) : (
        <div className="catalog-grid">
          {filtered.map((dataset) => (
            <Link href={`/catalog/${dataset.id}`} className="dataset-card" key={dataset.id}>
              <div className="dataset-card-head">
                <span className={`layer-badge layer-${dataset.layer}`}>{dataset.layer}</span>
                <Badge tone={classificationTone(dataset.classification)}>{dataset.classification}</Badge>
              </div>
              <h3>{dataset.name}</h3>
              <p>{dataset.description || "No business description yet."}</p>
              <div className="schema-chips">
                {(dataset.schema || []).slice(0, 4).map((column) => (
                  <span key={column.name} className={column.pii ? "pii" : ""}>{column.name}{column.pii ? " · PII" : ""}</span>
                ))}
                {(dataset.schema?.length || 0) > 4 && <span>+{(dataset.schema?.length || 0) - 4}</span>}
                {!dataset.schema && <span>{dataset.columns || 0} columns</span>}
              </div>
              <div className="dataset-card-meta">
                <span><strong>{number(dataset.row_count)}</strong> rows</span>
                <span>{bytes(dataset.size_bytes)}</span>
                <span>v{dataset.version}</span>
                <span>{relativeTime(dataset.updated_at)}</span>
              </div>
              <div className="dataset-card-foot">
                <span className="owner-dot"><ShieldCheck size={13} /> {dataset.owner || "unassigned"}</span>
                {dataset.can_read === false ? <Badge tone="warning">grant required</Badge> : <span className="text-link">Open <ArrowUpRight size={13} /></span>}
              </div>
            </Link>
          ))}
        </div>
      )}

      <div className="catalog-footnote">
        <History size={14} /> Metadata versions are immutable. Re-ingesting a dataset creates a new version and lineage edge.
        <span>Last sync {dateTime(new Date().toISOString())}</span>
      </div>
    </div>
  );
}
