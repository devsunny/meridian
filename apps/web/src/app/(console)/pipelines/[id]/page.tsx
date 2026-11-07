"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Workflow } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import type { Pipeline } from "@/lib/types";
import { Button, InlineError, Spinner } from "@/components/ui";

const DagEditor = dynamic(() => import("@/components/DagEditor"), {
  ssr: false,
  loading: () => <Spinner label="Loading DAG editor" />,
});

export default function PipelineEditorPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    if (!id) return;
    setLoading(true);
    try {
      setPipeline(await api.get<Pipeline>(`/pipelines/${id}`));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  if (loading) return <Spinner label="Loading workflow" />;
  if (error) return <InlineError message={error} />;
  if (!pipeline) return <InlineError message="Pipeline not found." />;

  return (
    <div className="page-stack editor-page">
      <div className="editor-breadcrumb">
        <Link href="/pipelines" className="back-link"><ArrowLeft size={15} /> Pipelines</Link>
        <span className="crumb-divider">/</span>
        <span>{pipeline.name}</span>
        <span className="editor-mode"><Workflow size={13} /> visual DAG</span>
      </div>
      <DagEditor pipeline={pipeline} onSaved={setPipeline} />
      <div className="editor-footnote">
        <span>Save creates an immutable pipeline version. Runs pin to the version they started with.</span>
        <Link href={`/runs?target_id=${pipeline.id}`}><Button variant="ghost" size="sm">Run history</Button></Link>
      </div>
    </div>
  );
}
