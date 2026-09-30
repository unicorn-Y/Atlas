export interface HealthResponse {
  status: 'ok' | string;
  version: string;
}

export interface ModelInfo {
  id: string;
  name?: string;
  provider?: string;
  [key: string]: unknown;
}

export interface ModelListResponse {
  models: ModelInfo[];
  current: string;
}

export interface ConfigurationResponse extends ModelListResponse {
  gateway_base_url: string;
  api_key_configured: boolean;
}

export interface CustomModelRequest {
  id: string;
  name: string;
  provider: string;
  litellm_model: string;
}

export interface ConnectionTestResponse {
  ok: boolean;
  model: string;
  message: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at?: string;
  pinned?: boolean;
  archived?: boolean;
  /** Working directory the conversation's last run used. */
  workspace?: string | null;
  /** Set once the conversation runs in its own git worktree. */
  worktree_path?: string | null;
  worktree_branch?: string | null;
  base_branch?: string | null;
  parent_conversation_id?: string | null;
  fork_message_id?: string | null;
  [key: string]: unknown;
}

export interface ConversationUpdate {
  title?: string;
  pinned?: boolean;
  archived?: boolean;
}

export interface ConversationCreateRequest {
  title?: string;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system' | string;
  content: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface ToolInfo {
  name: string;
  description: string;
  server: string;
  input_schema: Record<string, unknown>;
}

export interface ToolListResponse {
  servers: string[];
  tool_count: number;
  tools: ToolInfo[];
}

export interface RunStartRequest {
  type: 'run.start';
  run_id: string;
  content: string;
  conversation_id: string;
  model?: string;
  attachments?: string[];
  active_skills?: string[];
  /** `plan` explores read-only and waits for run.plan.approve before acting. */
  mode?: 'act' | 'plan';
  /** Absolute working directory for local tools; remembered per conversation. */
  workspace?: string;
  /** Non-image files: text is inlined, anything else is stored and its path passed to the Agent. */
  files?: RunFile[];
  /** Run in the conversation's own git worktree, created from base_branch on first use. */
  worktree?: { base_branch?: string };
  profile_id?: string;
  reasoning_effort?: ReasoningEffort;
  /** Workspace-relative files whose content is added to the message (@ mentions). */
  context_files?: string[];
  /** Other conversations summarised into the message (# mentions), at most three. */
  context_conversations?: string[];
  /** Side question: uses the conversation as context but is not saved to it; read-only tools. */
  ephemeral?: boolean;
}

export type ReasoningEffort = 'minimal' | 'low' | 'medium' | 'high';

export interface AgentProfile {
  id: string;
  name: string;
  description?: string;
  instructions?: string;
  model?: string | null;
  reasoning_effort?: ReasoningEffort | null;
  active_skills?: string[];
  tools?: { allow: string[] | null; deny: string[] };
  mode?: 'act' | 'plan';
}

export interface Recipe {
  id: string;
  name: string;
  description?: string;
  prompt: string;
  params: Array<{ name: string; label?: string; default?: string }>;
  active_skills?: string[];
  mode?: 'act' | 'plan';
  workspace?: string | null;
  profile_id?: string | null;
}

export interface WorktreeInfo {
  path: string;
  branch: string;
  base_branch: string;
  ahead: number;
  behind: number;
  dirty: boolean;
  changed_files: string[] | number;
}

export interface RunFile {
  name: string;
  mime: string;
  data_base64: string;
}

export interface RunChangeFile {
  path: string;
  workspace: string;
  status: 'added' | 'modified' | 'deleted';
  additions: number;
  deletions: number;
  diff: string;
  truncated?: boolean;
}

export interface WorkspaceEntry {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: number | null;
  git?: string | null;
}

export interface WorkspaceFile {
  path: string;
  content: string;
  truncated: boolean;
  binary: boolean;
}

export interface ProcessInfo {
  id: string;
  command: string;
  cwd?: string;
  status: 'running' | 'exited' | string;
  exit_code?: number | null;
  started_at?: string;
  run_id?: string | null;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  tags: string[];
}

export interface AgentCapabilityInfo {
  name: string;
  description: string;
  source: string;
}

export interface RuntimeEventEnvelope {
  type: 'agent_event';
  event_id: string;
  run_id: string;
  sequence: number;
  timestamp: string;
  event: string;
  data?: Record<string, unknown>;
}

export interface ApprovalResponse {
  type: 'approval.response';
  event_id: string;
  choice: 'allow' | 'deny';
}

export interface ResumeRequest {
  type: 'resume';
  run_id: string;
  after_sequence: number;
}

export type RuntimeStreamEvent = RuntimeEventEnvelope;

export interface Fact {
  key: string;
  value: string;
  category: string;
  [key: string]: unknown;
}

export interface KnowledgeEntry {
  id: string;
  content: string;
  source: string;
  category: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  [key: string]: unknown;
}

export interface MCPServerInfo {
  name: string;
  tool_count: number;
  tools: string[];
}

export interface MCPServerListResponse {
  servers: MCPServerInfo[];
}

export interface MCPServerAddRequest {
  name: string;
  transport: 'stdio' | 'sse';
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  url?: string;
}
