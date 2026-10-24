/** Typed REST clients for the persistent-Atlas backend (integration-map §5).
 *
 * Every function is a thin pass-through over the shared `api()` helper: the
 * endpoint paths and payload shapes mirror the Wave-1 routers exactly
 * (`core/atlas/api/*`). Group-chat routes follow the frozen W8 contract; when
 * the backend has not mounted them yet the fetch 404s and callers degrade to
 * the「群聊服务未就绪」placeholder instead of crashing.
 */
import { api } from './api';

// -- agents (W1) -------------------------------------------------------------

export interface AgentHeartbeat {
  enabled: boolean;
  interval_minutes: number;
  active_hours: string;
  prompt: string;
  delivery: string;
  isolated_session: boolean;
}
export interface AgentChannelBinding { channel: string; target: string; account?: string }
export interface AgentTable {
  enabled?: boolean;
  workspace?: string;
  heartbeat?: AgentHeartbeat;
  channels?: AgentChannelBinding[];
  device_preference?: string;
  browser_profile?: string;
  last_activity_at?: string;
  last_error?: string;
  last_status?: string;
}
export type AgentStatus = 'idle' | 'working' | 'waiting_user' | 'offline';
/** data/profiles/*.toml record (integration-map §3). */
export interface PersistentAgentRecord {
  id: string;
  name: string;
  description?: string;
  kind: 'role' | 'persistent';
  model?: string;
  reasoning_effort?: string;
  instructions?: string;
  active_skills?: string[];
  tools?: { allow?: string[]; deny?: string[] };
  mode?: string;
  created_at?: string;
  updated_at?: string;
  agent?: AgentTable;
  /** Runtime projection, only present for persistent agents. */
  status?: AgentStatus;
}
export interface AgentStatusProjection {
  agent_id: string;
  status: AgentStatus;
  error: string;
  last_activity_at: string;
  enabled: boolean;
}

export const agentsApi = {
  list: (base: string) =>
    api<{ agents: PersistentAgentRecord[] }>(base, '/api/agents?include_roles=true').then((body) => body.agents),
  create: (base: string, payload: Record<string, unknown>) =>
    api<PersistentAgentRecord>(base, '/api/agents', { method: 'POST', json: payload }),
  get: (base: string, id: string) =>
    api<PersistentAgentRecord>(base, `/api/agents/${encodeURIComponent(id)}`),
  patch: (base: string, id: string, patch: Record<string, unknown>) =>
    api<PersistentAgentRecord>(base, `/api/agents/${encodeURIComponent(id)}`, { method: 'PATCH', json: patch }),
  remove: (base: string, id: string) =>
    api<{ status: string }>(base, `/api/agents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  status: (base: string, id: string) =>
    api<AgentStatusProjection>(base, `/api/agents/${encodeURIComponent(id)}/status`),
  putHeartbeat: (base: string, id: string, config: Partial<AgentHeartbeat>) =>
    api<{ agent_id: string; heartbeat: AgentHeartbeat }>(base, `/api/agents/${encodeURIComponent(id)}/heartbeat`, { method: 'PUT', json: config }),
  listChannels: (base: string, id: string) =>
    api<{ agent_id: string; channels: AgentChannelBinding[] }>(base, `/api/agents/${encodeURIComponent(id)}/channels`),
  addChannel: (base: string, id: string, binding: AgentChannelBinding) =>
    api<{ channels: AgentChannelBinding[] }>(base, `/api/agents/${encodeURIComponent(id)}/channels`, { method: 'POST', json: binding }),
  removeChannel: (base: string, id: string, channel: string, target: string, account?: string) => {
    const query = new URLSearchParams({ channel, target, ...(account ? { account } : {}) });
    return api<{ channels: AgentChannelBinding[] }>(base, `/api/agents/${encodeURIComponent(id)}/channels?${query}`, { method: 'DELETE' });
  },
};

// -- per-agent skills + proposals (W7) ----------------------------------------

export interface AgentSkillRelation { skill_name: string; enabled: boolean; relation: string; note?: string | null }
export interface AgentSkillsView {
  agent_id: string;
  count: number;
  skills: string[];
  relations: AgentSkillRelation[];
}
export interface SkillProposal {
  proposal_id: string;
  skill_name: string;
  kind?: string;
  status: 'pending' | 'applied' | 'rejected' | string;
  revision_hash?: string;
  goal?: string;
  evidence?: string;
  created_by?: string;
  created_at?: string;
  diff?: { files?: Record<string, string>; writes?: Record<string, string>; deletes?: string[] };
  [key: string]: unknown;
}

export const agentSkillsApi = {
  list: (base: string, agentId: string) =>
    api<AgentSkillsView>(base, `/api/agents/${encodeURIComponent(agentId)}/skills`),
  set: (base: string, agentId: string, skills: Array<{ skill_name: string; enabled: boolean; relation?: string; note?: string }>) =>
    api<{ updated: number; relations: AgentSkillRelation[] }>(base, `/api/agents/${encodeURIComponent(agentId)}/skills`, { method: 'PUT', json: { skills } }),
  proposals: (base: string, status?: string) =>
    api<{ count: number; proposals: SkillProposal[] }>(base, `/api/skill-proposals${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  approve: (base: string, proposalId: string, reviewerNote = '') =>
    api<SkillProposal>(base, `/api/skill-proposals/${encodeURIComponent(proposalId)}/approve`, { method: 'POST', json: { reviewer_note: reviewerNote } }),
  reject: (base: string, proposalId: string, reason = '') =>
    api<SkillProposal>(base, `/api/skill-proposals/${encodeURIComponent(proposalId)}/reject`, { method: 'POST', json: { reason } }),
  rollback: (base: string, proposalId: string) =>
    api<SkillProposal>(base, `/api/skill-proposals/${encodeURIComponent(proposalId)}/rollback`, { method: 'POST', json: {} }),
};

// -- groups (W8, frozen paths; backend may not be mounted yet) ------------------

export interface GroupMember { agent_id: string; name?: string }
export interface GroupRecord {
  id: string;
  name: string;
  members?: GroupMember[];
  [key: string]: unknown;
}
export interface GroupTimelineEntry {
  id?: string;
  at?: string;
  actor?: string;
  actor_kind?: 'user' | 'agent' | 'system' | string;
  text?: string;
  [key: string]: unknown;
}

export const groupsApi = {
  list: (base: string) =>
    api<{ groups: GroupRecord[] }>(base, '/api/groups').then((body) => body.groups ?? []),
  create: (base: string, name: string, members: string[]) =>
    api<GroupRecord>(base, '/api/groups', { method: 'POST', json: { name, members: members.map((agent_id) => ({ agent_id })) } }),
  remove: (base: string, id: string) =>
    api<unknown>(base, `/api/groups/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  /** One participant turn: the user's text is appended and agents answer in turn. */
  turn: (base: string, id: string, text: string) =>
    api<unknown>(base, `/api/groups/${encodeURIComponent(id)}/turns`, { method: 'POST', json: { text } }),
  timeline: (base: string, id: string) =>
    api<{ entries?: GroupTimelineEntry[]; timeline?: GroupTimelineEntry[]; log?: GroupTimelineEntry[]; [key: string]: unknown }>(base, `/api/groups/${encodeURIComponent(id)}/timeline`),
  stop: (base: string, id: string) =>
    api<unknown>(base, `/api/groups/${encodeURIComponent(id)}/stop`, { method: 'POST' }),
};

// -- automations (W4) ---------------------------------------------------------

export interface AutomationTrigger {
  kind: 'cron' | 'interval' | 'date' | 'event' | 'webhook';
  cron_expr?: string;
  tz?: string;
  every_seconds?: number;
  at?: string;
  event_path?: string;
  event_glob?: string;
  event_debounce?: number;
}
export interface AutomationPayload {
  kind: 'agent_turn' | 'heartbeat' | 'script';
  message?: string;
  agent_id?: string;
  model?: string;
  skills?: string[];
  script?: string;
  timeout_seconds?: number;
  wake_mode?: '' | 'now' | 'next-heartbeat';
  execution_mode?: 'local' | 'worktree';
  base_directory?: string;
  cleanup_policy?: 'keep' | 'remove_after_run';
  worktree_path?: string;
  worktree_branch?: string;
  base_branch?: string;
}
export interface AutomationDelivery { mode: 'none' | 'channel'; channel?: string; target?: string }
export interface AutomationPolicy { missed_run?: 'catchup' | 'skip'; max_catchup?: number; delete_after_run?: boolean; consecutive_error_disable?: number }
export interface AutomationRecord {
  id: string;
  name: string;
  enabled: boolean;
  owner_agent_id?: string;
  trigger: AutomationTrigger;
  payload: AutomationPayload;
  delivery?: AutomationDelivery;
  policy?: AutomationPolicy;
  /** Runtime projection (display only). */
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  consecutive_errors?: number;
  paused_reason?: string | null;
}
export interface AutomationRun { workflow_id?: string; workflow_run_id?: string; started_at?: string; status?: string; result?: unknown; [key: string]: unknown }
export interface MigrationReport {
  source: string;
  imported_count: number;
  skipped_count: number;
  imported: Array<Record<string, unknown>>;
  skipped: Array<Record<string, unknown>>;
}

export const automationsApi = {
  list: (base: string) =>
    api<{ automations: AutomationRecord[]; engine_started: boolean }>(base, '/api/automations'),
  create: (base: string, payload: Record<string, unknown>) =>
    api<{ automation: AutomationRecord }>(base, '/api/automations', { method: 'POST', json: payload }),
  patch: (base: string, id: string, patch: Record<string, unknown>) =>
    api<{ automation: AutomationRecord }>(base, `/api/automations/${encodeURIComponent(id)}`, { method: 'PATCH', json: patch }),
  remove: (base: string, id: string) =>
    api<{ deleted: boolean }>(base, `/api/automations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  runNow: (base: string, id: string) =>
    api<Record<string, unknown>>(base, `/api/automations/${encodeURIComponent(id)}/run-now`, { method: 'POST' }),
  cancel: (base: string, id: string) =>
    api<Record<string, unknown>>(base, `/api/automations/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  pause: (base: string, id: string) =>
    api<Record<string, unknown>>(base, `/api/automations/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  resume: (base: string, id: string) =>
    api<Record<string, unknown>>(base, `/api/automations/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
    emergencyStatus: (base: string) => api<{ paused: boolean; affected?: Array<{ id: string; name?: string; cancelled?: number; error?: string }>; resumed?: string[]; failures?: Array<{ id: string; error: string }> }>(base, '/api/automations/global-pause'),
    emergencyPause: (base: string) => api<{ paused: boolean; affected?: Array<{ id: string; name?: string; cancelled?: number; error?: string }>; activity?: { stopped: Array<{ id: string; kind?: string; name?: string }>; failed: Array<{ id: string; kind?: string; name?: string; reason?: string }> }; resumed?: string[]; failures?: Array<{ id: string; error: string }> }>(base, '/api/automations/global-pause', { method: 'POST' }),
    emergencyResume: (base: string) => api<{ paused: boolean; affected?: Array<{ id: string; name?: string; cancelled?: number; error?: string }>; resumed?: string[]; failures?: Array<{ id: string; error: string }> }>(base, '/api/automations/global-resume', { method: 'POST' }),
  runs: (base: string, id: string, limit = 20) =>
    api<{ runs: AutomationRun[]; limit: number }>(base, `/api/automations/${encodeURIComponent(id)}/runs?limit=${limit}`),
  importLegacy: (base: string) =>
    api<MigrationReport>(base, '/api/automations/import-legacy', { method: 'POST', json: {} }),
  rotateWebhookSecret: (base: string, id: string) =>
    api<{ url: string; secret: string }>(base, `/api/automations/${encodeURIComponent(id)}/webhook/rotate-secret`, { method: 'POST', json: {} }),
};

// -- devices + takeover (W5) ---------------------------------------------------

export interface DeviceRecord {
  id: string;
  display_name: string;
  kind: string;
  os?: string;
  notes?: string;
  trusted?: boolean;
  online?: boolean;
  generation?: number;
  presence?: { state?: string; activity?: string; last_seen?: number };
  capabilities?: Record<string, unknown>;
  created_at?: string;
}
export interface TakeoverSnapshot {
  device_id: string;
  state: 'FREE' | 'HUMAN' | 'AGENT';
  holder: string;
  needs_observation?: boolean;
  since_ts?: number;
  pending_handoff?: number;
}
export interface TakeoverActivityEvent { ts?: number; actor?: string; event?: string; detail?: string; [key: string]: unknown }
export interface HandoffCard {
  card_id: string;
  note: string;
  status: 'PENDING' | 'done' | 'give_up' | string;
  created_ts?: number;
  created_by?: string;
  resolved_ts?: number | null;
  resolved_by?: string | null;
}

export const devicesApi = {
  list: (base: string) =>
    api<{ devices: DeviceRecord[]; self: string }>(base, '/api/devices'),
  register: (base: string, payload: { device_id: string; display_name: string; kind?: string; os?: string; notes?: string; trusted?: boolean }) =>
    api<DeviceRecord>(base, '/api/devices', { method: 'POST', json: payload }),
  patch: (base: string, id: string, patch: Record<string, unknown>) =>
    api<DeviceRecord>(base, `/api/devices/${encodeURIComponent(id)}`, { method: 'PATCH', json: patch }),
  remove: (base: string, id: string) =>
    api<unknown>(base, `/api/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  takeover: (base: string) =>
    api<TakeoverSnapshot>(base, '/api/devices/takeover'),
  takeoverAction: (base: string, action: 'human_take' | 'agent_take' | 'release', options: { agentId?: string; note?: string } = {}) =>
    api<Record<string, unknown>>(base, '/api/devices/takeover', {
      method: 'POST',
      json: { action, ...(options.agentId ? { agent_id: options.agentId } : {}), note: options.note ?? '' },
    }),
  activity: (base: string, limit = 30) =>
    api<{ activity: TakeoverActivityEvent[] }>(base, `/api/devices/activity?limit=${limit}`),
  handoff: (base: string) =>
    api<{ cards: HandoffCard[] }>(base, '/api/devices/handoff'),
  handoffAction: (base: string, action: 'open' | 'done' | 'give_up', options: { cardId?: string; note?: string } = {}) =>
    api<HandoffCard>(base, '/api/devices/handoff', {
      method: 'POST',
      json: { action, ...(options.cardId ? { card_id: options.cardId } : {}), note: options.note ?? '' },
    }),
};

// -- channel gateway (W2) -------------------------------------------------------

export interface ChannelStatusRow {
  name: string;
  enabled: boolean;
  running: boolean;
  paused?: boolean;
  last_error?: string;
  counts?: { received?: number; delivered?: number; dropped?: number; inbound_pending?: number; outbound?: number };
}
export interface ChannelGatewayStatus { channels: ChannelStatusRow[]; dispatcher_connected?: boolean }

export const channelsApi = {
  status: (base: string) =>
    api<ChannelGatewayStatus>(base, '/api/channels'),
  putAccounts: (base: string, configs: Record<string, Record<string, unknown>>) =>
    api<{ ok: boolean; configs: Record<string, Record<string, unknown>> }>(base, '/api/channels/accounts', { method: 'PUT', json: { configs } }),
  setCredential: (base: string, channel: string, field: string, value: string) =>
    api<{ ok: boolean; set: boolean }>(base, '/api/channels/credential', { method: 'POST', json: { channel, field, value } }),
  sendTest: (base: string, channel: string, chatId: string, text = '') =>
    api<{ ok: boolean; idempotency_key: string }>(base, '/api/channels/test', { method: 'POST', json: { channel, chat_id: chatId, text } }),
};

// -- managed local models (W6) ---------------------------------------------------

export interface LocalRuntimeStatus {
  enabled?: boolean;
  tag?: string | null;
  runtime_installed?: boolean;
  runtime_backend?: string | null;
  server_running?: boolean;
  server_base_url?: string | null;
  active_model_id?: string | null;
  loaded_models?: Record<string, unknown>;
  models?: Array<{ id: string; size_bytes?: number; size_label?: string }>;
  models_dir?: string;
  [key: string]: unknown;
}
export interface LocalHardware {
  uma?: boolean;
  vram_total_bytes?: number;
  ram_total_bytes?: number;
  ram_available_bytes?: number;
  vram_label?: string;
  gpu_name?: string | null;
  gpu_util_percent?: number | null;
  vram_used_bytes?: number | null;
  engine_devices?: Array<Record<string, unknown>>;
}
export interface LocalBackendRow {
  backend: string;
  package?: string;
  pinned_tag?: string | null;
  available?: boolean;
  unavailable_reason?: string | null;
  installed?: boolean;
  installed_tag?: string | null;
}
export interface LocalCatalogRow {
  id: string;
  display_name: string;
  description?: string;
  recommended?: boolean;
  recommended_reason?: string | null;
  fits?: boolean;
  fit_summary?: string;
  downloaded?: boolean;
  downloaded_model_id?: string | null;
  model_id?: string;
  quant?: string;
  size_label?: string;
  vision?: boolean;
  [key: string]: unknown;
}
export interface LocalJob {
  job_id: string;
  kind?: string;
  label?: string;
  status?: string;
  phase?: string;
  detail?: string;
  error?: string;
  done_bytes?: number;
  total_bytes?: number;
  percent?: number;
  bytes_per_sec?: number;
  eta_seconds?: number;
  can_pause?: boolean;
  can_resume?: boolean;
  model_id?: string;
  [key: string]: unknown;
}
export interface ActivationReport {
  model_id: string;
  ok: boolean;
  server_ok?: boolean;
  model_ready?: boolean;
  tool_call_ok?: boolean;
  detail?: Record<string, unknown>;
  diagnostics: string[];
  duration_ms?: number;
}

export const localModelsApi = {
  status: (base: string) => api<LocalRuntimeStatus>(base, '/api/local/models/status'),
  hardware: (base: string) => api<LocalHardware>(base, '/api/local/models/hardware'),
  backends: (base: string) => api<{ backends: LocalBackendRow[]; recommended?: string | null; recommended_unavailable_reason?: string | null }>(base, '/api/local/models/backends'),
  catalog: (base: string) => api<{ models: LocalCatalogRow[] }>(base, '/api/local/models/catalog'),
  search: (base: string, q: string, limit = 12) => api<{ hits: Array<Record<string, unknown>> }>(base, `/api/local/models/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  installRuntime: (base: string, backend?: string | null) => api<{ job_id: string }>(base, '/api/local/models/runtime/install', { method: 'POST', json: { backend: backend ?? null } }),
  download: (base: string, modelId: string) => api<{ job_id: string | null; already_downloaded?: boolean; model_id?: string }>(base, '/api/local/models/download', { method: 'POST', json: { model_id: modelId } }),
  pauseDownload: (base: string, jobId: string) => api<Record<string, unknown>>(base, '/api/local/models/download/pause', { method: 'POST', json: { job_id: jobId } }),
  resumeDownload: (base: string, jobId: string) => api<Record<string, unknown>>(base, '/api/local/models/download/resume', { method: 'POST', json: { job_id: jobId } }),
  jobs: (base: string) => api<{ jobs: LocalJob[] }>(base, '/api/local/models/jobs'),
  deleteModel: (base: string, modelId: string) => api<{ ok: boolean }>(base, `/api/local/models/models/${encodeURIComponent(modelId)}`, { method: 'DELETE' }),
  sideload: (base: string, path: string) => api<{ ok: boolean; model_id: string; already_present?: boolean }>(base, '/api/local/models/sideload', { method: 'POST', json: { path } }),
  server: (base: string, action: 'start' | 'stop') => api<Record<string, unknown>>(base, '/api/local/models/server', { method: 'POST', json: { action } }),
  activate: (base: string, modelId: string) => api<ActivationReport>(base, '/api/local/models/activate', { method: 'POST', json: { model_id: modelId } }),
  eject: (base: string, modelId: string) => api<{ ok: boolean }>(base, '/api/local/models/eject', { method: 'POST', json: { model_id: modelId } }),
  diagnostics: (base: string, jobId?: string) => api<Record<string, unknown>>(base, `/api/local/models/diagnostics${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`),
};
