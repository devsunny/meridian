"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Copy,
  FileJson,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Square,
  StepForward,
  TerminalSquare,
  X,
} from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { dateTime, duration, relativeTime } from "@/lib/format";
import type { LogEntry, Run, TaskRun } from "@/lib/types";
import { Badge, Button, InlineError, Spinner, StatusBadge } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

const RunGraph = dynamic(() => import("@/components/RunGraph"), { ssr: false, loading: () => <Spinner label="Loading graph" /> });

type Tab = "graph" | "logs" | "tasks" | "events" | "debug";

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const toast = useToast();
  const [run, setRun] = useState<Run | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [tab, setTab] = useState<Tab>("graph");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [level, setLevel] = useState("");
  const [logQuery, setLogQuery] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  async function load(silent = false) {
    if (!id) return;
    if (!silent) setLoading(true);
    try {
      const [detail, logPayload] = await Promise.all([
        api.get<Run>(`/runs/${id}`),
        api.get<{ entries: LogEntry[] }>(`/runs/${id}/logs?limit=2000`),
      ]);
      setRun(detail);
      setLogs(logPayload.entries);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [id]);

  useEffect(() => {
    if (tab === "logs" && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs, tab]);

  const pausedTask = run?.tasks?.find((task) => task.status === "PAUSED");
  const isTerminal = ["SUCCEEDED", "FAILED", "CANCELLED"].includes(run?.status || "");
  const active = run && !isTerminal;

  const filteredLogs = useMemo(
    () =>
      logs.filter((entry) => {
        if (level && entry.level !== level) return false;
        if (logQuery && !JSON.stringify(entry).toLowerCase().includes(logQuery.toLowerCase())) return false;
        return true;
      }),
    [logs, level, logQuery],
  );

  async function action(name: string, path: string, body?: unknown) {
    if (!id) return;
    setBusy(name);
    try {
      await api.post(path, body);
      toast.push(`Run ${name} requested.`, "success");
      await load(true);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setBusy("");
    }
  }

  if (loading && !run) return <Spinner label="Loading run" />;
  if (error && !run) return <InlineError message={error} />;
  if (!run) return <InlineError message="Run not found." />;

  const targetName = run.pipeline?.name || (run.kind === "ingestion" ? "Ingestion" : run.target_id.slice(0, 18));

  return (
    <div className="page-stack run-detail">
      <div className="run-back">
        <Link href="/runs" className="back-link"><ArrowLeft size={15} /> Runs</Link>
        <ChevronRight size={13} />
        <span>{run.id}</span>
      </div>

      <div className="run-header">
        <div className="run-heading">
          <div className="eyebrow">{run.kind} run · {run.trigger}</div>
          <h1>{targetName} {run.pipeline_version ? <span className="version-tag">v{run.pipeline_version}</span> : null}</h1>
          <div className="run-head-meta">
            <StatusBadge status={run.status} />
            {run.debug && <Badge tone="violet">debug mode</Badge>}
            {run.pause_requested && <Badge tone="warning">pause requested</Badge>}
            <span>Request <code className="request-code">{run.request_id}</code></span>
            <button className="icon-btn" aria-label="Copy request id" onClick={() => { void navigator.clipboard.writeText(run.request_id); toast.push("Request ID copied", "success"); }}><Copy size={14} /></button>
          </div>
        </div>
        <div className="run-actions">
          {active && !run.pause_requested && <Button variant="secondary" onClick={() => void action("pause", `/runs/${run.id}/pause`, {})} disabled={!!busy}><Pause size={15} /> Pause</Button>}
          {run.status === "PAUSED" && (
            <>
              <Button variant="primary" onClick={() => void action("resume", `/runs/${run.id}/resume`, { task_id: pausedTask?.task_id || null, note: "Web console" })} disabled={!!busy}><Play size={15} /> Resume</Button>
              <Button variant="secondary" onClick={() => void action("step", `/runs/${run.id}/step`, { task_id: pausedTask?.task_id || null })} disabled={!!busy}><StepForward size={15} /> Step</Button>
            </>
          )}
          {active && <Button variant="danger" onClick={() => void action("cancel", `/runs/${run.id}/cancel`)} disabled={!!busy}><Square size={14} /> Cancel</Button>}
          {isTerminal && <Button variant="secondary" onClick={() => void action("retry", `/runs/${run.id}/retry`)} disabled={!!busy}><RotateCcw size={15} /> Retry</Button>}
          <Button variant="ghost" onClick={() => void load(true)}><RefreshCw size={15} /></Button>
        </div>
      </div>

      {run.error && <div className="run-error"><strong>Run error.</strong> {run.error}</div>}
      {pausedTask?.type === "approval" && (
        <div className="approval-banner">
          <div>
            <Badge tone="warning">Approval required</Badge>
            <strong>{pausedTask.name}</strong>
            <span>{pausedTask.error || "A human approval is required before the workflow can continue."}</span>
          </div>
          <div className="row-actions">
            <Button variant="primary" onClick={() => void action("approve", `/runs/${run.id}/approve`, { task_id: pausedTask.task_id, approve: true, note: "Approved in console" })}><Check size={15} /> Approve</Button>
            <Button variant="danger" onClick={() => void action("reject", `/runs/${run.id}/approve`, { task_id: pausedTask.task_id, approve: false, note: "Rejected in console" })}><X size={15} /> Reject</Button>
          </div>
        </div>
      )}
      {error && <InlineError message={error} />}

      <div className="run-facts">
        <div><span>Started</span><strong>{dateTime(run.started_at)}</strong></div>
        <div><span>Duration</span><strong>{duration(run.started_at, run.ended_at)}</strong></div>
        <div><span>Tasks</span><strong>{run.tasks?.filter((task) => task.status === "SUCCEEDED").length || 0}/{run.tasks?.length || 0}</strong></div>
        <div><span>Created by</span><strong>{run.created_by}</strong></div>
        <div><span>Logical date</span><strong>{dateTime(run.logical_date)}</strong></div>
        <div><span>Debug</span><strong>{run.debug ? "enabled" : "off"}</strong></div>
      </div>

      <div className="tabs">
        {([
          ["graph", "Graph"],
          ["logs", "JSONL logs"],
          ["tasks", "Tasks"],
          ["events", "Events"],
          ["debug", "Debugger"],
        ] as Array<[Tab, string]>).map(([value, label]) => (
          <button key={value} className={`tab ${tab === value ? "active" : ""}`} onClick={() => setTab(value)}>
            {label}
            {value === "logs" && <span className="tab-count">{logs.length}</span>}
            {value === "tasks" && <span className="tab-count">{run.tasks?.length || 0}</span>}
          </button>
        ))}
      </div>

      {tab === "graph" && (
        <section className="panel run-panel">
          <RunGraph tasks={(run.tasks || []) as TaskRun[]} dag={run.pipeline?.dag} />
          <div className="graph-legend"><span className="legend success">succeeded</span><span className="legend info">running</span><span className="legend warning">paused</span><span className="legend danger">failed</span><span className="legend neutral">pending</span></div>
        </section>
      )}

      {tab === "logs" && (
        <section className="panel log-panel">
          <div className="log-toolbar">
            <div className="search-field compact"><TerminalSquare size={14} /><input value={logQuery} onChange={(event) => setLogQuery(event.target.value)} placeholder="Filter logs…" /></div>
            <select value={level} onChange={(event) => setLevel(event.target.value)}>
              <option value="">All levels</option><option>INFO</option><option>WARN</option><option>ERROR</option><option>DEBUG</option>
            </select>
            <span className="log-count">{filteredLogs.length} entries · jsonl</span>
            <Button size="sm" variant="ghost" onClick={() => { void navigator.clipboard.writeText(filteredLogs.map((entry) => JSON.stringify(entry)).join("\n")); toast.push("Logs copied", "success"); }}><Copy size={14} /> Copy</Button>
          </div>
          <div className="log-viewer" ref={logRef}>
            {filteredLogs.map((entry, index) => (
              <div className="log-line" key={`${entry.timestamp}-${index}`}>
                <span className="log-time">{entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString("en-US", { hour12: false }) : "—"}</span>
                <span className={`log-level level-${(entry.level || "INFO").toLowerCase()}`}>{entry.level || "INFO"}</span>
                <span className="log-msg">{entry.message}</span>
                {entry.task_id && <span className="log-task">{String(entry.task_id).slice(0, 18)}</span>}
                {entry.request_id && <span className="log-req">{String(entry.request_id).slice(0, 20)}</span>}
              </div>
            ))}
            {!filteredLogs.length && <div className="log-empty">No log entries yet. Workers append JSONL here as tasks execute.</div>}
          </div>
        </section>
      )}

      {tab === "tasks" && (
        <div className="task-list">
          {(run.tasks || []).map((task) => (
            <div className="task-card" key={task.id}>
              <div className="task-card-head">
                <div><span className="task-type">{task.type}</span><h3>{task.name}</h3></div>
                <StatusBadge status={task.status} />
              </div>
              <div className="task-meta">
                <span>Attempt {task.attempt}/{task.max_attempts}</span>
                <span>{duration(task.started_at, task.ended_at)}</span>
                <span>{task.worker_id || "unassigned"}</span>
                <code>{task.request_id}</code>
              </div>
              {task.error && <div className="task-error">{task.error}</div>}
              {Object.keys(task.output || {}).length > 0 && (
                <details>
                  <summary><FileJson size={14} /> Output</summary>
                  <pre>{JSON.stringify(task.output, null, 2)}</pre>
                </details>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === "events" && (
        <section className="panel">
          <div className="event-list">
            {(run.events || []).slice().reverse().map((event) => (
              <div className="event-row" key={event.seq}>
                <div className="event-seq">{event.seq}</div>
                <div className="event-body"><div className="event-type">{event.type}</div><p>{event.message}</p><code>{event.request_id}</code></div>
                <span className="event-time">{relativeTime(event.created_at)}</span>
              </div>
            ))}
            {!run.events?.length && <p className="muted pad">No events recorded.</p>}
          </div>
        </section>
      )}

      {tab === "debug" && (
        <section className="panel debug-panel">
          <div className="debug-head">
            <div><h2>Remote debugger</h2><p>Breakpoints pause the DAG before the selected task. The worker releases the lease so you can inspect state and resume.</p></div>
            <Badge tone={run.debug ? "violet" : "neutral"}>{run.debug ? "debug session" : "standard run"}</Badge>
          </div>
          <div className="debug-grid">
            <div className="debug-card">
              <span>Paused task</span>
              <strong>{pausedTask?.name || "None"}</strong>
              <small>{pausedTask ? `${pausedTask.type} · ${pausedTask.error || "breakpoint"}` : "The run is not waiting."}</small>
            </div>
            <div className="debug-card">
              <span>Breakpoints</span>
              <strong>{run.tasks?.filter((task) => task.breakpoint).length || 0}</strong>
              <small>{run.tasks?.filter((task) => task.breakpoint).map((task) => task.name).join(", ") || "Set a breakpoint in the DAG editor."}</small>
            </div>
            <div className="debug-card">
              <span>Worker lease</span>
              <strong>{pausedTask?.worker_id || run.tasks?.find((task) => task.status === "RUNNING")?.worker_id || "released"}</strong>
              <small>Leases are claimed with SKIP LOCKED; paused tasks are not consumed.</small>
            </div>
          </div>
          <div className="debug-actions">
            <Button variant="primary" disabled={run.status !== "PAUSED"} onClick={() => void action("resume", `/runs/${run.id}/resume`, { task_id: pausedTask?.task_id || null, note: "Resume from debugger" })}><Play size={15} /> Resume to next breakpoint</Button>
            <Button variant="secondary" disabled={run.status !== "PAUSED"} onClick={() => void action("step", `/runs/${run.id}/step`, { task_id: pausedTask?.task_id || null })}><StepForward size={15} /> Step one task</Button>
            <Link href={run.pipeline ? `/pipelines/${run.pipeline.id}` : "/pipelines"}><Button variant="ghost">Edit breakpoints</Button></Link>
          </div>
          <div className="debug-note">Tip: run a pipeline with <strong>Debug</strong> instead of <strong>Run</strong>. It pauses before every task marked with a breakpoint and preserves the same request ID in all logs.</div>
        </section>
      )}

      <div className="request-footer">Run {run.id} · request <code>{run.request_id}</code></div>
    </div>
  );
}
