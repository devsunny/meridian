"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Connection as FlowConnection,
  Controls,
  Edge,
  Handle,
  MarkerType,
  Node,
  NodeProps,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import {
  ArrowDownToLine,
  Bell,
  CheckCircle2,
  Circle,
  Code2,
  GitBranch,
  Globe,
  Loader2,
  Play,
  Plus,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserCheck,
  Zap,
} from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import type { Dag, Ingestion, Integration, Pipeline, TaskDefinition } from "@/lib/types";
import { Badge, Button, Field, InlineError } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

export interface EditorNodeData extends Record<string, unknown> {
  label: string;
  taskType: string;
  config: Record<string, unknown>;
  breakpoint: boolean;
  maxAttempts?: number;
}

type TaskNode = Node<EditorNodeData, "task">;

interface TaskType {
  type: string;
  label: string;
  category: string;
  description: string;
  fields: Array<{ name: string; label: string; type: string; default?: unknown; options?: string[] }>;
}

const ICONS: Record<string, React.ReactNode> = {
  "ingestion.run": <ArrowDownToLine size={15} />,
  "sql.transform": <Code2 size={15} />,
  "quality.check": <ShieldCheck size={15} />,
  "http.request": <Globe size={15} />,
  "etl.trigger": <Zap size={15} />,
  "ai.generate": <Sparkles size={15} />,
  approval: <UserCheck size={15} />,
  notify: <Bell size={15} />,
  noop: <Circle size={15} />,
};

const TONES: Record<string, string> = {
  "ingestion.run": "source",
  "sql.transform": "transform",
  "quality.check": "quality",
  "http.request": "action",
  "etl.trigger": "integration",
  "ai.generate": "ai",
  approval: "control",
  notify: "action",
  noop: "control",
};

const DEFAULTS: Record<string, Record<string, unknown>> = {
  "ingestion.run": { ingestion_id: "" },
  "sql.transform": { sql: "SELECT * FROM input LIMIT 1000", target_dataset: "silver_output", layer: "silver" },
  "quality.check": { min_rows: 1 },
  "http.request": { url: "https://", method: "GET" },
  "etl.trigger": { external_system_id: "" },
  "ai.generate": { prompt: "Summarise the upstream documents with citations.", top_k: 6 },
  approval: { message: "Approve promotion to the gold layer." },
  notify: { message: "Pipeline reached a checkpoint." },
  noop: {},
};

export function TaskNodeView({ data, selected }: NodeProps<TaskNode>) {
  const tone = TONES[data.taskType] || "control";
  return (
    <div className={`flow-node tone-${tone} ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-node-head">
        <span className="flow-node-icon">{ICONS[data.taskType] || <GitBranch size={15} />}</span>
        <span className="flow-node-type">{data.taskType}</span>
        {data.breakpoint && <span className="breakpoint-dot" title="Debug breakpoint" />}
      </div>
      <strong>{data.label}</strong>
      <span className="flow-node-foot">{data.taskType === "sql.transform" ? String(data.config.target_dataset || "SQL") : data.taskType === "quality.check" ? "gate" : "task"}</span>
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  );
}

function toFlow(dag: Dag): { nodes: TaskNode[]; edges: Edge[] } {
  const nodes = (dag.nodes || []).map((node, index) => ({
    id: node.id,
    type: "task" as const,
    position: node.position || { x: 80 + (index % 4) * 250, y: 120 + Math.floor(index / 4) * 150 },
    data: {
      label: node.name || node.id,
      taskType: node.type,
      config: node.config || {},
      breakpoint: !!node.breakpoint,
      maxAttempts: node.max_attempts,
    },
  }));
  const edgeList: Edge[] = [];
  const seen = new Set<string>();
  (dag.edges || []).forEach((edge) => {
    const key = `${edge.source}->${edge.target}`;
    if (!seen.has(key) && edge.source !== edge.target) {
      seen.add(key);
      edgeList.push({ id: key, source: edge.source, target: edge.target, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed }, animated: false });
    }
  });
  (dag.nodes || []).forEach((node) => {
    (node.depends_on || []).forEach((source) => {
      const key = `${source}->${node.id}`;
      if (!seen.has(key)) {
        seen.add(key);
        edgeList.push({ id: key, source, target: node.id, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } });
      }
    });
  });
  return { nodes, edges: edgeList };
}

function toDag(nodes: TaskNode[], edges: Edge[]): Dag {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      name: node.data.label,
      type: node.data.taskType,
      config: node.data.config,
      breakpoint: node.data.breakpoint,
      max_attempts: node.data.maxAttempts,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      depends_on: edges.filter((edge) => edge.target === node.id).map((edge) => edge.source),
    })),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
  };
}

function uniqueId(base: string, nodes: TaskNode[]): string {
  const stem = base.replace(/[^a-zA-Z0-9_]/g, "_").replace(/^[^a-zA-Z]/, "task_") || "task";
  if (!nodes.some((node) => node.id === stem)) return stem;
  let index = 2;
  while (nodes.some((node) => node.id === `${stem}_${index}`)) index += 1;
  return `${stem}_${index}`;
}

export default function DagEditor({ pipeline: initial, onSaved }: { pipeline: Pipeline; onSaved?: (pipeline: Pipeline) => void }) {
  const toast = useToast();
  const [pipeline, setPipeline] = useState(initial);
  const [nodes, setNodes, onNodesChange] = useNodesState<TaskNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
  const [ingestions, setIngestions] = useState<Ingestion[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);

  useEffect(() => {
    const flow = toFlow(initial.dag);
    setNodes(flow.nodes);
    setEdges(flow.edges);
    setPipeline(initial);
    setName(initial.name);
    setDescription(initial.description);
    setDirty(false);
  }, [initial, setNodes, setEdges]);

  useEffect(() => {
    Promise.all([
      api.get<TaskType[]>("/pipelines/task-types"),
      api.get<Ingestion[]>("/ingestions"),
      api.get<Integration[]>("/integrations"),
    ])
      .then(([types, ingestionsRows, integrationRows]) => {
        setTaskTypes(types);
        setIngestions(ingestionsRows);
        setIntegrations(integrationRows);
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  const nodeTypes = useMemo(() => ({ task: TaskNodeView }), []);
  const selectedNode = nodes.find((node) => node.id === selected) || null;

  const onConnect = useCallback(
    (connection: FlowConnection) => {
      if (connection.source === connection.target) return;
      setEdges((current) =>
        addEdge(
          { ...connection, id: `${connection.source}->${connection.target}`, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } },
          current,
        ),
      );
      setDirty(true);
    },
    [setEdges],
  );

  function updateNode(patch: Partial<EditorNodeData>) {
    if (!selected) return;
    setNodes((current) => current.map((node) => (node.id === selected ? { ...node, data: { ...node.data, ...patch } } : node)));
    setDirty(true);
  }

  function updateConfig(key: string, value: unknown) {
    if (!selectedNode) return;
    updateNode({ config: { ...selectedNode.data.config, [key]: value } });
  }

  function addNode(taskType: string) {
    const type = taskTypes.find((item) => item.type === taskType);
    const id = uniqueId(taskType.split(".")[0], nodes);
    const node: TaskNode = {
      id,
      type: "task",
      position: { x: 120 + (nodes.length % 4) * 245, y: 100 + Math.floor(nodes.length / 4) * 150 },
      data: {
        label: type?.label || taskType,
        taskType,
        config: { ...(DEFAULTS[taskType] || {}) },
        breakpoint: false,
        maxAttempts: 3,
      },
    };
    setNodes((current) => [...current, node]);
    setSelected(id);
    setDirty(true);
  }

  function removeSelected() {
    if (!selected) return;
    setNodes((current) => current.filter((node) => node.id !== selected));
    setEdges((current) => current.filter((edge) => edge.source !== selected && edge.target !== selected));
    setSelected(null);
    setDirty(true);
  }

  async function save(thenRun = false, debug = false) {
    setSaving(true);
    setError("");
    try {
      const dag = toDag(nodes, edges);
      const updated = await api.patch<Pipeline>(`/pipelines/${pipeline.id}`, { name, description, dag });
      setPipeline(updated);
      setDirty(false);
      onSaved?.(updated);
      toast.push(`Saved pipeline version ${updated.current_version}.`, "success");
      if (thenRun) {
        const run = await api.post<{ id: string }>(`/pipelines/${pipeline.id}/run`, { debug });
        toast.push(debug ? "Debug run queued. It will pause at the first breakpoint." : "Run queued.", "success");
        window.location.href = `/runs/${run.id}`;
      }
    } catch (err) {
      setError(errorMessage(err));
      toast.push(errorMessage(err), "error");
    } finally {
      setSaving(false);
      setRunning(false);
    }
  }

  async function validate() {
    try {
      const result = await api.post<{ valid: boolean; nodes: number }>("/pipelines/validate", { nodes: toDag(nodes, edges).nodes, edges: toDag(nodes, edges).edges });
      toast.push(`DAG valid · ${result.nodes} tasks`, "success");
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  return (
    <div className="editor-shell">
      <div className="editor-header">
        <div className="editor-title">
          <div className="eyebrow">DAG editor · v{pipeline.current_version}</div>
          <input className="title-input" value={name} onChange={(event) => { setName(event.target.value); setDirty(true); }} />
          <input className="subtitle-input" value={description} onChange={(event) => { setDescription(event.target.value); setDirty(true); }} placeholder="Add a description" />
        </div>
        <div className="editor-actions">
          {dirty && <span className="dirty-pill">Unsaved changes</span>}
          <Button variant="ghost" onClick={() => void validate()}>Validate</Button>
          <Button variant="secondary" onClick={() => void save(false)} disabled={saving}>{saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save</Button>
          <Button variant="dark" onClick={() => void save(true, false)} disabled={saving || running}><Play size={15} /> Run</Button>
          <Button variant="primary" onClick={() => void save(true, true)} disabled={saving}><Zap size={15} /> Debug</Button>
        </div>
      </div>
      {error && <InlineError message={error} />}
      <div className={`editor-body ${selectedNode ? "with-inspector" : ""}`}>
        <aside className="palette">
          <div className="palette-head"><strong>Task palette</strong><span>{taskTypes.length} types</span></div>
          <div className="palette-list">
            {taskTypes.map((type) => (
              <button key={type.type} className="palette-item" onClick={() => addNode(type.type)} title={type.description}>
                <span className={`palette-icon tone-${TONES[type.type] || "control"}`}>{ICONS[type.type] || <GitBranch size={15} />}</span>
                <span><strong>{type.label}</strong><small>{type.category}</small></span>
                <Plus size={13} />
              </button>
            ))}
          </div>
          <div className="palette-tip">
            <Badge tone="violet">Debug</Badge>
            <p>Select a task and mark it as a breakpoint. Run in debug mode, inspect logs, then resume or step.</p>
          </div>
        </aside>

        <div className="canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={(changes) => { onNodesChange(changes); if (changes.some((change) => change.type === "position" && change.dragging === false)) setDirty(true); }}
            onEdgesChange={(changes) => { onEdgesChange(changes); setDirty(true); }}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelected(node.id)}
            onPaneClick={() => setSelected(null)}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.24, maxZoom: 1.05 }}
            proOptions={{ hideAttribution: true }}
            minZoom={0.3}
            maxZoom={1.6}
          >
            <Background color="#cdd6e6" gap={22} size={1.2} />
            <Controls showInteractive={false} />
          </ReactFlow>
          {nodes.length === 0 && (
            <div className="canvas-empty">
              <GitBranch size={26} />
              <h3>Start with a task</h3>
              <p>Add a source, SQL transform or quality gate from the palette.</p>
            </div>
          )}
        </div>

        <aside className={`inspector ${selectedNode ? "open" : ""}`}>
          {selectedNode ? (
            <>
              <div className="inspector-head">
                <div>
                  <div className="eyebrow">Selected task</div>
                  <h3>{selectedNode.data.label}</h3>
                </div>
                <button className="icon-btn danger" onClick={removeSelected} aria-label="Delete task"><Trash2 size={16} /></button>
              </div>
              <div className="inspector-body">
                <Field label="Task label">
                  <input value={selectedNode.data.label} onChange={(event) => updateNode({ label: event.target.value })} />
                </Field>
                <Field label="Task type">
                  <select
                    value={selectedNode.data.taskType}
                    onChange={(event) => {
                      const type = event.target.value;
                      updateNode({ taskType: type, config: { ...(DEFAULTS[type] || {}) } });
                    }}
                  >
                    {taskTypes.map((type) => <option key={type.type} value={type.type}>{type.label}</option>)}
                  </select>
                </Field>
                <div className="inspector-divider">Configuration</div>
                {renderConfig(selectedNode.data.taskType, selectedNode.data.config, updateConfig, ingestions, integrations)}
                <div className="inspector-divider">Reliability & debug</div>
                <label className="checkbox-row">
                  <input type="checkbox" checked={selectedNode.data.breakpoint} onChange={(event) => updateNode({ breakpoint: event.target.checked })} />
                  Pause at breakpoint in debug mode
                </label>
                <Field label="Max attempts">
                  <input type="number" min={1} max={10} value={selectedNode.data.maxAttempts || 3} onChange={(event) => updateNode({ maxAttempts: Number(event.target.value) })} />
                </Field>
                <div className="node-id">task id <code>{selectedNode.id}</code></div>
              </div>
            </>
          ) : (
            <div className="inspector-empty">
              <GitBranch size={22} />
              <h3>Inspector</h3>
              <p>Select a task to edit its configuration, retries or breakpoint.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function renderConfig(
  taskType: string,
  config: Record<string, unknown>,
  update: (key: string, value: unknown) => void,
  ingestions: Ingestion[],
  integrations: Integration[],
) {
  switch (taskType) {
    case "ingestion.run":
      return (
        <Field label="Ingestion" required hint="Runs the configured connector and registers a dataset version.">
          <select value={String(config.ingestion_id || "")} onChange={(event) => update("ingestion_id", event.target.value)}>
            <option value="">Select ingestion…</option>
            {ingestions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </Field>
      );
    case "sql.transform":
      return (
        <>
          <Field label="SQL" hint="Use the `input` view for the first upstream dataset." required>
            <textarea className="code-input" rows={9} value={String(config.sql || "")} onChange={(event) => update("sql", event.target.value)} />
          </Field>
          <Field label="Target dataset">
            <input value={String(config.target_dataset || "")} onChange={(event) => update("target_dataset", event.target.value)} />
          </Field>
          <Field label="Layer">
            <select value={String(config.layer || "silver")} onChange={(event) => update("layer", event.target.value)}>
              <option value="bronze">Bronze</option><option value="silver">Silver</option><option value="gold">Gold</option><option value="sandbox">Sandbox</option>
            </select>
          </Field>
        </>
      );
    case "quality.check":
      return (
        <>
          <Field label="Minimum rows">
            <input type="number" min={0} value={Number(config.min_rows || 1)} onChange={(event) => update("min_rows", Number(event.target.value))} />
          </Field>
          <Field label="Required columns" hint="Comma separated.">
            <input value={Array.isArray(config.required_columns) ? (config.required_columns as string[]).join(", ") : String(config.required_columns || "")} onChange={(event) => update("required_columns", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} />
          </Field>
          <Field label="Unique column">
            <input value={String(config.unique_column || "")} onChange={(event) => update("unique_column", event.target.value)} />
          </Field>
          <Field label="Max null %">
            <input type="number" min={0} max={100} value={config.max_null_pct === undefined ? "" : Number(config.max_null_pct)} onChange={(event) => update("max_null_pct", event.target.value === "" ? undefined : Number(event.target.value))} />
          </Field>
        </>
      );
    case "approval":
      return (
        <Field label="Approval message">
          <textarea rows={3} value={String(config.message || "")} onChange={(event) => update("message", event.target.value)} />
        </Field>
      );
    case "ai.generate":
      return (
        <>
          <Field label="Prompt" hint="Grounded in upstream document datasets.">
            <textarea rows={5} value={String(config.prompt || "")} onChange={(event) => update("prompt", event.target.value)} />
          </Field>
          <Field label="Passages">
            <input type="number" min={1} max={20} value={Number(config.top_k || 6)} onChange={(event) => update("top_k", Number(event.target.value))} />
          </Field>
        </>
      );
    case "etl.trigger":
      return (
        <>
          <Field label="External system">
            <select value={String(config.external_system_id || "")} onChange={(event) => update("external_system_id", event.target.value)}>
              <option value="">Select integration…</option>
              {integrations.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.type}</option>)}
            </select>
          </Field>
          <Field label="Provider config" hint="dag_id, job_id, connector_id or connection_id depending on provider.">
            <textarea className="code-input" rows={4} value={JSON.stringify(config.config || {}, null, 2)} onChange={(event) => {
              try { update("config", JSON.parse(event.target.value)); } catch { /* keep editing */ }
            }} />
          </Field>
        </>
      );
    case "http.request":
      return (
        <>
          <Field label="URL"><input value={String(config.url || "")} onChange={(event) => update("url", event.target.value)} /></Field>
          <Field label="Method">
            <select value={String(config.method || "GET")} onChange={(event) => update("method", event.target.value)}>
              {["GET", "POST", "PUT", "PATCH"].map((method) => <option key={method}>{method}</option>)}
            </select>
          </Field>
          <Field label="JSON body">
            <textarea className="code-input" rows={4} value={JSON.stringify(config.body || {}, null, 2)} onChange={(event) => {
              try { update("body", JSON.parse(event.target.value)); } catch { /* keep editing */ }
            }} />
          </Field>
        </>
      );
    default:
      return (
        <Field label="Config JSON">
          <textarea className="code-input" rows={6} value={JSON.stringify(config, null, 2)} onChange={(event) => {
            try { Object.entries(JSON.parse(event.target.value)).forEach(([key, value]) => update(key, value)); } catch { /* keep editing */ }
          }} />
        </Field>
      );
  }
}
