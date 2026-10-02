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
  compression_model: string;
  subagents_enabled?: boolean;
  subagent_default_model?: string;
}

export interface CustomModelRequest {
  id: string;
  name: string;
  provider: string;
  litellm_model: string;
  /** Longest reply the model may write; the backend default is 16384. */
  max_output_tokens?: number;
  /** Per million tokens, in the currency the user thinks in; enables cost estimates. */
  price?: { input?: number; output?: number; cached_input?: number };
}

export type UsageGroup = 'day' | 'conversation' | 'model';

export interface UsageTotals {
  runs: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  /** cached / input; null when nothing was sent. */
  cache_hit_rate: number | null;
  /** null when any record in the group has no known price. */
  est_cost: number | null;
}

export interface UsageRow extends UsageTotals { key: string; label: string }

export interface UsageReport { rows: UsageRow[]; totals: UsageTotals }

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
  permission_mode?: PermissionMode | null;
  fork_message_id?: string | null;
  /** Extra absolute directories the Agent may touch besides the workspace. */
  allowed_paths?: string[] | null;
  /** `atlas` or an external Agent id (codex, claude…). */
  executor?: string | null;
  sandbox?: SandboxSettings | null;
  /** Further directories this conversation works in, besides `workspace` (at most 5). */
  extra_roots?: string[] | null;
  /** Where the conversation came from, e.g. `telegram` for tasks sent from the phone. */
  source?: string | null;
  [key: string]: unknown;
}

export interface ConversationUpdate {
  title?: string;
  pinned?: boolean;
  archived?: boolean;
  workspace?: string;
  permission_mode?: PermissionMode;
  allowed_paths?: string[];
  executor?: string;
  /** `null` turns the sandbox off. */
  sandbox?: SandboxSettings | null;
  extra_roots?: string[];
}

export interface RewindResult { rewind_id: string; removed_messages: number; restored_files: string[]; skipped: Array<{ path: string; reason: string }> }
export interface CustomTool {
  id: string; name: string; description: string; command: string[];
  input_schema: Record<string, unknown>; timeout_s: number; enabled: boolean;
}
export interface TelegramSettings {
  enabled: boolean; bot_token_set: boolean; allowed_user_ids: number[]; default_workspace: string;
  notify_on: Array<'completed' | 'failed' | 'approval'>;
}
export interface ProjectSource {
  id: string; kind: 'file' | 'folder' | 'url' | 'note'; title: string; path?: string | null; url?: string | null;
  text?: string | null; bytes: number; added_at: string;
}
export interface ProjectSources { instructions: string; sources: ProjectSource[] }

export interface SandboxSettings { type: 'docker'; image?: string; network?: boolean }
export interface ExternalAgentInfo { id: string; name: string; available: boolean; version: string | null; detail: string }
export interface SandboxStatus { docker: { available: boolean; version: string | null; detail: string } }
export interface WorkspaceVersion {
  id: string; run_id: string | null; conversation_id: string | null; created_at: string; bytes: number; source: 'checkpoint' | 'git';
}
export interface CheckItem { file?: string; line?: number; col?: number; severity: 'error' | 'warning' | 'info'; code?: string; message: string; test?: string }
export interface CheckResults {
  kind: string; tool: string; passed: number; failed: number; skipped: number; duration_ms?: number; items: CheckItem[];
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
  /** FULL_ACCESS is the default; stricter modes ask before writes or refuse them. */
  permission_mode?: PermissionMode;
  allowed_paths?: string[];
  extra_roots?: string[];
  executor?: string;
  sandbox?: SandboxSettings | null;
}

export type PermissionMode = 'full_access' | 'ask_each' | 'ask_writes' | 'auto_file' | 'plan' | 'read_only';

export interface HookConfig { id: string; event: string; command: string; timeout_s: number; enabled: boolean }

export interface PullRequestInfo {
  number: number; title: string; url: string; state: string; draft: boolean; base: string; head: string;
  checks: Array<{ name: string; status: string; conclusion: string | null; url?: string | null }>;
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
