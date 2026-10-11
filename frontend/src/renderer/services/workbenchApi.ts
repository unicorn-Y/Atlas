/** 工作台（挂件）后端接口：/api/workbench/*、/ws/workbench/*。 */

export type WorkbenchMode = 'acp' | 'terminal' | 'command';

export interface WorkbenchAgent {
  id: string; name: string; mode: WorkbenchMode; command: string; args: string[]; env: Record<string, string>;
  description: string; version: string; source: string; icon: string; repository: string;
  isolate_config: boolean; permission: 'ask' | 'allow'; enabled: boolean; cwd: string;
  created_at: number; updated_at: number; folder: string; workspace: string; running: number;
}

export interface RegistryAgent {
  id: string; name: string; version: string; description: string; icon: string; repository: string; license: string;
  install: 'npx' | 'uvx' | 'binary' | null;
}

export interface SessionSnapshot {
  id: string; agent_id: string; status: string; busy: boolean; acp_session_id: string | null;
  info: SessionInfo; pending_permissions: string[];
}

export interface SessionInfo {
  agent?: { name?: string; title?: string; version?: string } | null;
  auth_methods?: Array<{ id: string; name: string; description?: string }>;
  load_session?: boolean;
  modes?: { currentModeId: string; availableModes: Array<{ id: string; name: string; description?: string }> } | null;
  config_options?: Array<{ id: string; name: string; type?: string; currentValue?: string | boolean; options?: Array<{ value: string; name: string }> }>;
}

export interface WorkbenchEvent { kind: string; t?: number; [key: string]: unknown }

export interface HistoryItem { id: string; title: string; updated_at: number }

async function call<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  } catch {
    throw new Error('连不上 Atlas 后端');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
const id = encodeURIComponent;

export const workbenchApi = (base: string) => ({
  agents: () => call<{ agents: WorkbenchAgent[]; root: string }>(base, '/api/workbench/agents'),
  create: (manifest: Partial<WorkbenchAgent>) => call<WorkbenchAgent>(base, '/api/workbench/agents', post({ manifest })),
  createTemplate: (name: string) => call<WorkbenchAgent>(base, '/api/workbench/agents/template', post({ name })),
  update: (agentId: string, manifest: Partial<WorkbenchAgent>) =>
    call<WorkbenchAgent>(base, `/api/workbench/agents/${id(agentId)}`, { method: 'PUT', body: JSON.stringify({ manifest, confirm: true }) }),
  setEnabled: (agentId: string, enabled: boolean) => call<WorkbenchAgent>(base, `/api/workbench/agents/${id(agentId)}/enabled`, post({ enabled })),
  remove: (agentId: string) => call<{ deleted: string }>(base, `/api/workbench/agents/${id(agentId)}?confirm=true`, { method: 'DELETE' }),
  upgrade: (agentId: string) => call<WorkbenchAgent>(base, `/api/workbench/agents/${id(agentId)}/upgrade`, post({ confirm: true })),
  registry: (refresh = false) => call<{ agents: RegistryAgent[]; platform: string }>(base, `/api/workbench/registry${refresh ? '?refresh=true' : ''}`),
  install: (registryId: string) => call<WorkbenchAgent>(base, `/api/workbench/registry/${id(registryId)}/install`, post({})),
  sessions: (agentId: string) => call<{ history: HistoryItem[]; running: SessionSnapshot[] }>(base, `/api/workbench/agents/${id(agentId)}/sessions`),
  start: (agentId: string, resume?: string) => call<SessionSnapshot>(base, `/api/workbench/agents/${id(agentId)}/sessions`, post({ resume: resume ?? null })),
  events: (agentId: string, sessionId: string) => call<{ events: WorkbenchEvent[] }>(base, `/api/workbench/agents/${id(agentId)}/sessions/${id(sessionId)}/events`),
  deleteSession: (agentId: string, sessionId: string) => call<unknown>(base, `/api/workbench/agents/${id(agentId)}/sessions/${id(sessionId)}`, { method: 'DELETE' }),
  prompt: (sessionId: string, text: string) => call<SessionSnapshot>(base, `/api/workbench/sessions/${id(sessionId)}/prompt`, post({ text })),
  cancel: (sessionId: string) => call<SessionSnapshot>(base, `/api/workbench/sessions/${id(sessionId)}/cancel`, post({})),
  permission: (sessionId: string, requestId: string, optionId: string | null) =>
    call<SessionSnapshot>(base, `/api/workbench/sessions/${id(sessionId)}/permission`, post({ request_id: requestId, option_id: optionId })),
  authenticate: (sessionId: string, methodId: string) => call<SessionSnapshot>(base, `/api/workbench/sessions/${id(sessionId)}/authenticate`, post({ method_id: methodId })),
  setMode: (sessionId: string, modeId: string) => call<SessionSnapshot>(base, `/api/workbench/sessions/${id(sessionId)}/mode`, post({ mode_id: modeId })),
  setOption: (sessionId: string, configId: string, value: string | boolean) =>
    call<SessionSnapshot>(base, `/api/workbench/sessions/${id(sessionId)}/option`, post({ config_id: configId, value })),
  close: (sessionId: string) => call<unknown>(base, `/api/workbench/sessions/${id(sessionId)}/close`, post({})),
  streamUrl: (sessionId: string) => `${base.replace(/^http/, 'ws')}/ws/workbench/sessions/${id(sessionId)}`,
  terminalUrl: (agentId: string, shell = false) => `${base.replace(/^http/, 'ws')}/ws/workbench/agents/${id(agentId)}/terminal${shell ? '?shell=true' : ''}`,
});

export type WorkbenchApi = ReturnType<typeof workbenchApi>;
