export interface JobRunTask {
  id: string;
  task_id: string;
  name: string;
  type: string;
  status: string;
  attempt: number;
  max_attempts: number;
  depends_on: string[];
  output: Record<string, unknown>;
  error: string | null;
  worker_id: string | null;
  request_id: string;
  started_at: string | null;
  ended_at: string | null;
  spec: Record<string, unknown>;
}
