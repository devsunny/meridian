export type Role = "admin" | "steward" | "engineer" | "analyst" | "auditor" | "viewer";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  role_label?: string;
  tenant_id: string;
  tenant_slug: string;
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
  request_id: string;
}

export interface Dashboard {
  tenant: { id: string; slug: string; name: string };
  counts: {
    connections: number;
    ingestions: number;
    pipelines: number;
    datasets: number;
    schedules: number;
    active_runs: number;
    storage_bytes: number;
    rows: number;
    success_rate: number;
  };
  recent_runs: Run[];
  upcoming_schedules: Array<{
    id: string;
    name: string;
    cron: string;
    next_run_at: string | null;
    target_type: string;
  }>;
  role: Role;
  request_id: string;
}

export interface ConnectorField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  default: unknown;
  help: string;
  options: string[];
}

export interface Connector {
  type: string;
  label: string;
  category: string;
  description: string;
  capabilities: string[];
  config_schema: ConnectorField[];
  icon: string;
}

export interface Connection {
  id: string;
  name: string;
  type: string;
  description: string;
  config: Record<string, unknown>;
  secret_ref: string | null;
  has_secret: boolean;
  status: string;
  owner: string;
  last_tested_at: string | null;
  last_test_ok: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface Resource {
  id: string;
  name: string;
  kind: string;
  path?: string | null;
  size?: number | null;
  modified_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface Ingestion {
  id: string;
  name: string;
  description: string;
  connection_id: string;
  target_dataset: string;
  spec: Record<string, unknown>;
  schedule_cron: string | null;
  schedule_timezone: string;
  status: string;
  owner: string;
  last_run_id: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskDefinition {
  id: string;
  name?: string;
  type: string;
  config: Record<string, unknown>;
  depends_on?: string[];
  position?: { x: number; y: number };
  breakpoint?: boolean;
  max_attempts?: number;
  timeout_seconds?: number;
}

export interface DagEdge {
  source: string;
  target: string;
}

export interface Dag {
  nodes: TaskDefinition[];
  edges: DagEdge[];
}

export interface Pipeline {
  id: string;
  name: string;
  description: string;
  owner: string;
  status: string;
  current_version: number;
  dag: Dag;
  created_at: string;
  updated_at: string;
}

export interface Schedule {
  id: string;
  name: string;
  target_type: string;
  target_id: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  catchup: boolean;
  max_concurrent_runs: number;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
}

export interface TaskRun {
  id: string;
  task_id: string;
  name: string;
  type: string;
  status: string;
  attempt: number;
  max_attempts: number;
  depends_on: string[];
  breakpoint?: boolean;
  output: Record<string, unknown>;
  error: string | null;
  worker_id: string | null;
  request_id: string;
  started_at: string | null;
  ended_at: string | null;
  spec: Record<string, unknown>;
}

export interface Run {
  id: string;
  kind: string;
  target_id: string;
  pipeline_version: number | null;
  status: string;
  trigger: string;
  request_id: string;
  logical_date: string | null;
  debug: boolean;
  pause_requested: boolean;
  created_by: string;
  schedule_id: string | null;
  error: string | null;
  output: Record<string, unknown>;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  tasks?: TaskRun[];
  task_graph?: { nodes: Array<{ id: string; name: string; type: string; status: string; depends_on: string[] }> };
  events?: RunEvent[];
  pipeline?: { id: string; name: string; version: number; dag: Dag } | null;
}

export interface RunEvent {
  seq: number;
  type: string;
  message: string;
  data: Record<string, unknown>;
  request_id: string;
  created_at: string;
}

export interface LogEntry {
  timestamp?: string;
  level: string;
  message: string;
  request_id?: string;
  run_id?: string;
  task_id?: string;
  [key: string]: unknown;
}

export interface DatasetColumn {
  name: string;
  type: string;
  nullable: boolean;
  pii: boolean;
  pii_kind?: string | null;
  classification: string;
  description: string;
}

export interface Dataset {
  id: string;
  name: string;
  description: string;
  layer: string;
  format: string;
  classification: string;
  owner: string;
  row_count: number;
  size_bytes: number;
  version: number;
  columns?: number;
  schema?: DatasetColumn[];
  profile?: Record<string, unknown>;
  pii_columns?: string[];
  source_uri: string;
  can_read?: boolean;
  updated_at: string;
  created_at: string;
  lineage?: LineageGraph;
}

export interface LineageGraph {
  root: string;
  nodes: Array<{
    id: string;
    name: string;
    layer: string;
    classification: string;
    row_count: number;
    is_root: boolean;
  }>;
  edges: Array<{ id: string; source: string; target: string; operation: string; run_id: string | null }>;
}

export interface AccessRequest {
  id: string;
  requester_email: string;
  dataset_id: string;
  dataset?: { id: string; name: string; classification: string } | null;
  action: string;
  purpose: string;
  duration_days: number;
  status: string;
  decision_reason: string;
  expires_at: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface AccessGrant {
  id: string;
  principal_email: string;
  dataset_id: string;
  action: string;
  granted_by: string;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  seq: number;
  actor_email: string;
  action: string;
  resource_type: string;
  resource_id: string;
  outcome: string;
  request_id: string;
  ip: string;
  data: Record<string, unknown>;
  hash: string;
  created_at: string;
}

export interface GovernanceSummary {
  datasets: number;
  by_classification: Record<string, number>;
  pii_columns: Array<{
    dataset_id: string;
    dataset: string;
    column: string;
    kind: string;
    classification: string;
    owner: string;
  }>;
  pending_access_requests: number;
  active_grants: number;
  audit_chain: { valid: boolean; checked: number; head_hash: string; message: string };
}

export interface Soc2Report {
  framework: string;
  generated_at: string;
  audit_chain: { valid: boolean; checked: number; head_hash: string; message: string };
  latest_audit_seq: number;
  open_access_requests: number;
  controls: Array<{ id: string; name: string; status: string; evidence: string }>;
  retention: Record<string, string>;
}

export interface ExternalSystem {
  id: string;
  name: string;
  type: string;
  base_url: string;
  secret_ref: string | null;
  has_secret: boolean;
  config: Record<string, unknown>;
  enabled: boolean;
  status: string;
  last_tested_at: string | null;
  created_at: string;
}

export type Integration = ExternalSystem;

export interface PlatformUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  role_label: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface AssistantAnswer {
  answer: string;
  mode: string;
  model: string;
  citations: Array<{
    index: number;
    title: string;
    page: number | null;
    source_uri: string;
    dataset_id: string;
    snippet: string;
  }>;
  catalog: Array<{ id: string; name: string; description: string; layer: string; rows: number }>;
  request_id: string;
}

export interface QueryResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  request_id: string;
}
