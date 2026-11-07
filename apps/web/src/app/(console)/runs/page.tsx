"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowUpRight, Filter, Play, RefreshCw, Search } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { dateTime, duration, relativeTime } from "@/lib/format";
import type { Pipeline, Run } from "@/lib/types";
import { Badge, Button, EmptyState, InlineError, PageHeader, Spinner, StatusBadge } from "@/components/ui";

export default function RunsPage() {
  const params = useSearchParams();
  const targetId = params.get("target_id");
  const [runs, setRuns] = useState<Run[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [query, setQuery] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const queryParams = new URLSearchParams({ limit: "100" });
      if (targetId) queryParams.set("target_id", targetId);
      const [rows, pipelineRows] = await Promise.all([api.get<Run[]>(`/runs?${queryParams}`), api.get<Pipeline[]>("/pipelines")]);
      setRuns(rows);
      setPipelines(pipelineRows);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [targetId]);

  const names = useMemo(() => Object.fromEntries(pipelines.map((pipeline) => [pipeline.id, pipeline.name])), [pipelines]);
  const filtered = runs.filter((run) => {
    if (statusFilter && run.status !== statusFilter) return false;
    if (kindFilter && run.kind !== kindFilter) return false;
    if (query && !`${run.id} ${run.request_id} ${names[run.target_id] || ""}`.toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Operations"
        title="Runs & debugging"
        description="Trace every task by one request ID across scheduler, worker and connector. Pause, resume, approve and retry without redeploying."
        actions={<Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /> Refresh</Button>}
      />

      {error && <InlineError message={error} />}

      <div className="metric-strip">
        <div><span>Total visible</span><strong>{runs.length}</strong></div>
        <div><span>Running</span><strong>{runs.filter((run) => run.status === "RUNNING").length}</strong></div>
        <div><span>Paused</span><strong>{runs.filter((run) => run.status === "PAUSED").length}</strong></div>
        <div><span>Failed</span><strong>{runs.filter((run) => run.status === "FAILED").length}</strong></div>
      </div>

      <div className="toolbar">
        <div className="search-field"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search run or request id…" /></div>
        <div className="filter-group">
          <Filter size={14} />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All statuses</option>
            {["QUEUED", "RUNNING", "PAUSED", "SUCCEEDED", "FAILED", "CANCELLED"].map((status) => <option key={status}>{status}</option>)}
          </select>
          <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}>
            <option value="">All kinds</option>
            <option value="pipeline">Pipeline</option>
            <option value="ingestion">Ingestion</option>
          </select>
        </div>
      </div>

      {loading && !runs.length ? (
        <Spinner label="Loading runs" />
      ) : filtered.length === 0 ? (
        <EmptyState icon={<Play size={24} />} title="No runs match" description="Trigger an ingestion or pipeline, or clear the filters." />
      ) : (
        <div className="table-card">
          <div className="table-wrap">
            <table className="data-table run-table">
              <thead><tr><th>Run</th><th>Target</th><th>Status</th><th>Trigger</th><th>Duration</th><th>Request ID</th><th>Started</th><th /></tr></thead>
              <tbody>
                {filtered.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link href={`/runs/${run.id}`} className="mono-link">{run.id.slice(0, 18)}…</Link>
                      <div className="cell-sub">{run.kind}{run.debug ? " · debug" : ""}</div>
                    </td>
                    <td>
                      <div className="cell-title">{names[run.target_id] || run.target_id.slice(0, 18)}</div>
                      {run.pipeline_version && <div className="cell-sub">version {run.pipeline_version}</div>}
                    </td>
                    <td><StatusBadge status={run.status} />{run.pause_requested && <Badge tone="warning">pause requested</Badge>}</td>
                    <td className="muted">{run.trigger}</td>
                    <td className="muted">{duration(run.started_at, run.ended_at)}</td>
                    <td><code className="request-code">{run.request_id.slice(0, 22)}…</code></td>
                    <td className="muted">{relativeTime(run.created_at)}</td>
                    <td><Link href={`/runs/${run.id}`} className="row-arrow"><ArrowUpRight size={14} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div className="request-footer">Auto-refreshes every 5 seconds · timestamps {dateTime(new Date().toISOString())}</div>
    </div>
  );
}
