"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  CalendarClock,
  Database,
  GitBranch,
  Layers3,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Timer,
  Workflow,
} from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { bytes, dateTime, number, relativeTime, statusTone } from "@/lib/format";
import type { AssistantAnswer, Dashboard, Dataset } from "@/lib/types";
import { Badge, Button, InlineError, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { useAuth } from "@/components/AuthProvider";

function Metric({
  icon,
  label,
  value,
  detail,
  tone = "indigo",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <div className="metric-card">
      <div className={`metric-icon tone-${tone}`}>{icon}</div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [question, setQuestion] = useState("What is our refund approval policy?");
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null);
  const [asking, setAsking] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [dashboard, catalog] = await Promise.all([api.get<Dashboard>("/dashboard"), api.get<Dataset[]>("/datasets")]);
      setData(dashboard);
      setDatasets(catalog);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const layers = useMemo(() => {
    const counts: Record<string, number> = {};
    datasets.forEach((dataset) => {
      counts[dataset.layer] = (counts[dataset.layer] || 0) + 1;
    });
    return counts;
  }, [datasets]);

  const pendingClassification = datasets.filter((dataset) => ["confidential", "restricted"].includes(dataset.classification)).length;
  const totalRuns = data?.recent_runs.length || 0;
  const succeeded = data?.recent_runs.filter((run) => run.status === "SUCCEEDED").length || 0;

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    try {
      setAnswer(await api.post<AssistantAnswer>("/assist/ask", { question, top_k: 4 }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAsking(false);
    }
  }

  if (loading && !data) return <Spinner label="Loading workspace" />;
  if (error && !data) return <InlineError message={error} />;

  const firstName = user?.name.split(" ")[0] || "there";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={`${new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date())} · ${data?.tenant.name}`}
        title={`${greeting}, ${firstName}.`}
        description="Your governed data plane is healthy. Here is what moved, what needs attention, and what your teams can ask next."
        actions={
          <>
            <Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /> Refresh</Button>
            <Link href="/pipelines"><Button variant="primary"><Workflow size={16} /> Build a pipeline</Button></Link>
          </>
        }
      />

      {error && <InlineError message={error} />}

      <div className="notice-strip">
        <div className="notice-icon"><ShieldCheck size={17} /></div>
        <div>
          <strong>{pendingClassification} {pendingClassification === 1 ? "asset carries" : "assets carry"} confidential or restricted data.</strong>
          <span> Access is grant-gated and every read is audit-logged with a shared request ID.</span>
        </div>
        <Link href="/governance">Review governance <ArrowUpRight size={14} /></Link>
      </div>

      <div className="metrics-grid">
        <Metric icon={<Layers3 size={19} />} label="Governed datasets" value={number(data?.counts.datasets)} detail={`${number(data?.counts.rows)} rows · ${bytes(data?.counts.storage_bytes)}`} />
        <Metric icon={<GitBranch size={19} />} label="Active workflows" value={number(data?.counts.pipelines)} detail={`${number(data?.counts.schedules)} schedules armed`} tone="violet" />
        <Metric icon={<PlayCircle size={19} />} label="Runs in flight" value={number(data?.counts.active_runs)} detail={`${data?.counts.success_rate ?? 100}% success rate`} tone="cyan" />
        <Metric icon={<Database size={19} />} label="Connected sources" value={number(data?.counts.connections)} detail={`${number(data?.counts.ingestions)} ingestion definitions`} tone="amber" />
      </div>

      <div className="dashboard-grid">
        <section className="panel panel-large">
          <div className="panel-head">
            <div>
              <h2>Recent runs</h2>
              <p>Every run carries one request ID across API, scheduler and worker.</p>
            </div>
            <Link href="/runs" className="text-link">All runs <ArrowUpRight size={14} /></Link>
          </div>
          <div className="run-health">
            <div className="health-copy">
              <span className="health-value">{succeeded}/{totalRuns || 0}</span>
              <span>recent runs succeeded</span>
            </div>
            <div className="health-bars" aria-hidden="true">
              {(data?.recent_runs || []).slice().reverse().map((run) => (
                <span key={run.id} className={`health-bar bar-${statusTone(run.status)}`} title={run.status} />
              ))}
              {!data?.recent_runs.length && <span className="muted">No runs yet</span>}
            </div>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>Run</th><th>Kind</th><th>Status</th><th>Trigger</th><th>Request ID</th><th>When</th><th /></tr>
              </thead>
              <tbody>
                {data?.recent_runs.map((run) => (
                  <tr key={run.id}>
                    <td><Link className="mono-link" href={`/runs/${run.id}`}>{run.id.slice(0, 16)}…</Link></td>
                    <td className="capitalize">{run.kind}</td>
                    <td><StatusBadge status={run.status} /></td>
                    <td className="muted">{run.trigger}</td>
                    <td><code className="request-code">{run.request_id.slice(0, 20)}…</code></td>
                    <td className="muted">{relativeTime(run.created_at)}</td>
                    <td><Link href={`/runs/${run.id}`} className="row-arrow"><ArrowUpRight size={14} /></Link></td>
                  </tr>
                ))}
                {!data?.recent_runs.length && (
                  <tr><td colSpan={7} className="table-empty">No runs yet. Open a pipeline and start one.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div><h2>Next scheduled</h2><p>Materialised by the scheduler service.</p></div>
            <CalendarClock size={18} className="panel-icon" />
          </div>
          <div className="schedule-list">
            {data?.upcoming_schedules.map((schedule) => (
              <div className="schedule-item" key={schedule.id}>
                <div className="schedule-time">{schedule.next_run_at ? dateTime(schedule.next_run_at) : "paused"}</div>
                <div className="schedule-name">{schedule.name}</div>
                <Badge tone="neutral">{schedule.target_type}</Badge>
              </div>
            ))}
            {!data?.upcoming_schedules.length && <p className="muted pad">No schedules armed.</p>}
          </div>
          <Link href="/schedules" className="panel-link">Manage schedules <ArrowUpRight size={14} /></Link>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div><h2>Lakehouse layers</h2><p>Raw → bronze → silver → gold.</p></div>
            <Layers3 size={18} className="panel-icon" />
          </div>
          <div className="layer-list">
            {["raw", "bronze", "silver", "gold"].map((layer) => (
              <div className="layer-row" key={layer}>
                <span className={`layer-dot layer-${layer}`} />
                <span className="capitalize">{layer}</span>
                <div className="layer-track"><span style={{ width: `${Math.min(100, ((layers[layer] || 0) / Math.max(1, datasets.length)) * 100 + 4)}%` }} /></div>
                <strong>{layers[layer] || 0}</strong>
              </div>
            ))}
          </div>
          <Link href="/catalog" className="panel-link">Open catalog <ArrowUpRight size={14} /></Link>
        </section>

        <section className="panel assistant-panel">
          <div className="panel-head">
            <div>
              <h2><Sparkles size={17} /> Ask Meridian</h2>
              <p>ACL-aware retrieval over governed documents, with citations.</p>
            </div>
            <Badge tone="violet">RAG</Badge>
          </div>
          <form onSubmit={ask} className="assistant-form">
            <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask across governed documents…" />
            <Button variant="dark" type="submit" disabled={asking}>{asking ? <Timer size={15} /> : <Sparkles size={15} />}</Button>
          </form>
          {answer ? (
            <div className="assistant-answer">
              <div className="answer-meta"><Badge tone={answer.mode === "llm" ? "violet" : "neutral"}>{answer.mode}</Badge><span>{answer.citations.length} citations</span></div>
              <p>{answer.answer.slice(0, 900)}{answer.answer.length > 900 ? "…" : ""}</p>
              <div className="citation-chips">
                {answer.citations.slice(0, 3).map((citation) => <span key={citation.index}>[{citation.index}] {citation.title}</span>)}
              </div>
            </div>
          ) : (
            <div className="assistant-placeholder">
              <Sparkles size={22} />
              <span>Try “What is the refund approval threshold?”</span>
            </div>
          )}
          <Link href="/assistant" className="panel-link">Open assistant <ArrowUpRight size={14} /></Link>
        </section>
      </div>

      <div className="request-footer">Last dashboard request · <code>{data?.request_id}</code> · all timestamps UTC</div>
    </div>
  );
}
