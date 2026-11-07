"use client";

import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { Background, Controls, Edge, MarkerType, Node, ReactFlow } from "@xyflow/react";
import type { JobRunTask } from "./run-types";

interface RunNodeData extends Record<string, unknown> {
  label: string;
  type: string;
  status: string;
}

const TONE: Record<string, string> = {
  SUCCEEDED: "success",
  FAILED: "danger",
  RUNNING: "info",
  QUEUED: "info",
  PENDING: "neutral",
  PAUSED: "warning",
  CANCELLED: "danger",
  SKIPPED: "neutral",
};

function RunNode({ data }: { data: RunNodeData }) {
  return (
    <div className={`run-node run-${TONE[data.status] || "neutral"}`}>
      <div className="run-node-top"><span className="run-dot" /><span>{data.type}</span></div>
      <strong>{data.label}</strong>
      <small>{data.status.replace(/_/g, " ").toLowerCase()}</small>
    </div>
  );
}

export default function RunGraph({ tasks, dag }: { tasks: JobRunTask[]; dag?: { nodes?: Array<{ id: string; position?: { x: number; y: number } }>; edges?: Array<{ source: string; target: string }> } | null }) {
  const { nodes, edges } = useMemo(() => {
    const positions = new Map((dag?.nodes || []).map((node) => [node.id, node.position]));
    const flowNodes: Node<RunNodeData>[] = tasks.map((task, index) => ({
      id: task.task_id,
      type: "run",
      position: positions.get(task.task_id) || { x: 80 + (index % 4) * 230, y: 100 + Math.floor(index / 4) * 130 },
      data: { label: task.name, type: task.type, status: task.status },
      draggable: false,
    }));
    const flowEdges: Edge[] = [];
    if (dag?.edges?.length) {
      dag.edges.forEach((edge) => flowEdges.push({ id: `${edge.source}-${edge.target}`, source: edge.source, target: edge.target, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } }));
    } else {
      tasks.forEach((task) => (task.depends_on || []).forEach((source) => flowEdges.push({ id: `${source}-${task.task_id}`, source, target: task.task_id, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } })));
    }
    return { nodes: flowNodes, edges: flowEdges };
  }, [tasks, dag]);

  const nodeTypes = useMemo(() => ({ run: RunNode }), []);

  return (
    <div className="run-graph">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView proOptions={{ hideAttribution: true }} nodesDraggable={false} nodesConnectable={false} elementsSelectable>
        <Background color="#d7dfeb" gap={22} size={1.1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
