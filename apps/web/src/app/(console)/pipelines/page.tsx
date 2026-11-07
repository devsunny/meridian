"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, GitBranch, Layers, Play, Plus, RefreshCw, Workflow } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { Pipeline } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

interface Template {
  id: string;
  name: string;
  description: string;
  dag: Pipeline["dag"];
}

export default function PipelinesPage() {
  const router = useRouter();
  const toast = useToast();
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateId, setTemplateId] = useState("medallion");
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [rows, templateRows] = await Promise.all([api.get<Pipeline[]>("/pipelines"), api.get<Template[]>("/pipelines/templates")]);
      setPipelines(rows);
      setTemplates(templateRows);
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
      const template = templates.find((item) => item.id === templateId);
      const pipeline = await api.post<Pipeline>("/pipelines", {
        name,
        description,
        owner: "",
        dag: template?.dag || { nodes: [], edges: [] },
      });
      toast.push("Pipeline created. Add tasks and save a version.", "success");
      setOpen(false);
      router.push(`/pipelines/${pipeline.id}`);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function run(pipeline: Pipeline) {
    setRunningId(pipeline.id);
    try {
      const run = await api.post<{ id: string }>(`/pipelines/${pipeline.id}/run`, { debug: false });
      toast.push("Pipeline run queued.", "success");
      router.push(`/runs/${run.id}`);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Orchestration"
        title="Pipelines"
        description="Versioned DAGs with parallel branches, dependencies, retries, quality gates, approvals and breakpoint debugging."
        actions={
          <>
            <Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /></Button>
            <Button variant="primary" onClick={() => { setName(""); setDescription(""); setTemplateId("medallion"); setOpen(true); }}><Plus size={16} /> New pipeline</Button>
          </>
        }
      />

      {error && <InlineError message={error} />}

      <div className="pipeline-hero">
        <div>
          <div className="eyebrow light">Execution model</div>
          <h2>Declare the graph. Let the platform handle the rest.</h2>
          <p>One scheduler, leased task queue and stateless workers. Every task shares the run request ID and writes JSONL logs.</p>
          <div className="hero-tags"><span>Parallel</span><span>Retries</span><span>Quality gates</span><span>Human approval</span><span>Breakpoints</span></div>
        </div>
        <div className="hero-graphic" aria-hidden="true">
          <span className="hg-node a">extract</span><i /><span className="hg-node b">clean</span><i /><span className="hg-node c">gate</span><i /><span className="hg-node d">gold</span>
        </div>
      </div>

      {loading ? (
        <Spinner label="Loading pipelines" />
      ) : pipelines.length === 0 ? (
        <EmptyState icon={<Workflow size={24} />} title="No pipelines yet" description="Start from a template and edit the DAG visually." action={<Button variant="primary" onClick={() => setOpen(true)}><Plus size={16} /> Create pipeline</Button>} />
      ) : (
        <div className="cards-grid pipeline-cards">
          {pipelines.map((pipeline) => (
            <article className="pipeline-card" key={pipeline.id}>
              <div className="pipeline-card-top">
                <div className="pipeline-icon"><GitBranch size={19} /></div>
                <StatusBadge status={pipeline.status} />
              </div>
              <Link href={`/pipelines/${pipeline.id}`} className="pipeline-title">{pipeline.name}</Link>
              <p>{pipeline.description || "No description yet."}</p>
              <div className="pipeline-stats">
                <span><Layers size={14} /> {pipeline.dag.nodes?.length || 0} tasks</span>
                <span><GitBranch size={14} /> v{pipeline.current_version}</span>
                <span>{pipeline.owner || "unassigned"}</span>
              </div>
              <div className="pipeline-card-foot">
                <span className="muted">Updated {relativeTime(pipeline.updated_at)}</span>
                <div className="row-actions">
                  <Link href={`/pipelines/${pipeline.id}`} className="text-link">Edit <ArrowUpRight size={13} /></Link>
                  <Button size="sm" variant="secondary" onClick={() => void run(pipeline)} disabled={runningId === pipeline.id}>
                    <Play size={13} /> {runningId === pipeline.id ? "Starting…" : "Run"}
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Create pipeline"
        subtitle="Pick a starting graph. You can edit every task, edge and breakpoint in the visual editor."
        width="lg"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="pipeline-form" disabled={saving}>{saving ? "Creating…" : "Create & edit"}</Button></>}
      >
        <form id="pipeline-form" onSubmit={create} className="form-grid">
          <Field label="Pipeline name" required>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Customer Revenue Daily" required minLength={2} />
          </Field>
          <Field label="Description">
            <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Bronze orders → silver → gold revenue" />
          </Field>
          <Field label="Starting template">
            <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
              {templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
            </select>
          </Field>
          <div className="template-preview">
            <div className="template-title">{templates.find((item) => item.id === templateId)?.name}</div>
            <p>{templates.find((item) => item.id === templateId)?.description}</p>
            <div className="template-flow">
              {templates.find((item) => item.id === templateId)?.dag.nodes.map((node) => (
                <div key={node.id} className="template-node"><strong>{node.name || node.id}</strong><span>{node.type}</span></div>
              ))}
            </div>
          </div>
        </form>
      </Modal>
    </div>
  );
}
