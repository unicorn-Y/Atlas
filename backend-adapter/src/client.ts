import { mockConversations, mockModels, mockTools, streamMockRun } from './mock';
import type { AgentCapabilityInfo, ApprovalResponse, ConfigurationResponse, ConnectionTestResponse, ConversationCreateRequest, ConversationMessage, ConversationSummary, ConversationUpdate, CustomModelRequest, Fact, KnowledgeEntry, MCPServerAddRequest, MCPServerInfo, MCPServerListResponse, ModelListResponse, AgentProfile, HookConfig, ProcessInfo, PullRequestInfo, Recipe, ResumeRequest, WorktreeInfo, RunChangeFile, RunStartRequest, RuntimeEventEnvelope, RuntimeStreamEvent, SkillInfo, ToolListResponse, WorkspaceEntry, WorkspaceFile } from './types';

export interface BackendAdapterOptions {
  baseUrl: string;
}

export class BackendAdapter {
  readonly baseUrl: string;
  private live = false;
  private activeRuns = new Set<string>();
  private mockCancelled = new Set<string>();
  private mockControls = new Map<string, (event: string, data?: Record<string, unknown>) => void>();
  private runSockets = new Map<string, WebSocket>();
  private approvalResolvers = new Map<string, { runId: string; resolve: (choice: 'allow' | 'deny') => void }>();
  /** Agent Runtime protocol version as [major, minor]; [1, 0] for backends that predate the endpoint. */
  private runtimeProtocol: [number, number] | null = null;
  availabilityError: string | null = null;

  constructor(options: BackendAdapterOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
  }

  get mode(): 'mock' | 'backend' { return this.live ? 'backend' : 'mock'; }
  get apiBaseUrl(): string { return this.baseUrl; }

  async initialize(timeoutMs = 1200): Promise<'mock' | 'backend'> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}/api/health`, { signal: controller.signal });
      this.live = response.ok;
      this.availabilityError = response.ok ? null : `Backend health check failed (${response.status})`;
    } catch (error) {
      this.live = false;
      this.availabilityError = error instanceof Error ? error.message : 'Backend is unavailable';
    } finally {
      clearTimeout(timeout);
    }
    return this.mode;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...init?.headers },
      });
    } catch (error) {
      this.live = false;
      this.availabilityError = error instanceof Error ? error.message : 'Backend request failed';
      throw error;
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string };
      const message = body.detail ?? `Backend request failed (${response.status})`;
      if (response.status >= 500) {
        this.live = false;
        this.availabilityError = message;
      }
      throw new Error(message);
    }
    this.availabilityError = null;
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  private hasEventProtocol(): boolean {
    const [major, minor] = this.runtimeProtocol ?? [0, 0];
    return major > 1 || (major === 1 && minor >= 2);
  }

  private async supportsRuntimeProtocol(): Promise<boolean> {
    if (this.runtimeProtocol === null) {
      try {
        const response = await fetch(`${this.baseUrl}/api/runtime/protocol`);
        const body = response.ok ? await response.json() as { version?: string } : {};
        // Minor versions only add messages, so any version from 1.2 up speaks the event protocol.
        const [major, minor] = (body.version ?? '').split('.').map((part) => Number.parseInt(part, 10));
        this.runtimeProtocol = Number.isInteger(major) ? [major, Number.isInteger(minor) ? minor : 0] : [1, 0];
      } catch {
        this.runtimeProtocol = [1, 0];
      }
    }
    return this.hasEventProtocol();
  }

  async getModels(): Promise<ModelListResponse> { return this.live ? this.request('/api/models') : mockModels; }
  async getConfiguration(): Promise<ConfigurationResponse> {
    if (this.live) return this.request('/api/settings/configuration');
    return { ...mockModels, gateway_base_url: this.baseUrl, api_key_configured: false };
  }
  async updateConfiguration(gatewayBaseUrl: string, apiKey: string): Promise<ConfigurationResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存 API 配置');
    return this.request('/api/settings/configuration', { method: 'PUT', body: JSON.stringify({ gateway_base_url: gatewayBaseUrl, api_key: apiKey || null }) });
  }
  async addCustomModel(model: CustomModelRequest): Promise<ConfigurationResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存自定义模型');
    return this.request('/api/models/custom', { method: 'POST', body: JSON.stringify(model) });
  }
  async testConnection(model?: string): Promise<ConnectionTestResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能测试模型连接');
    return this.request('/api/settings/test-connection', { method: 'POST', body: JSON.stringify({ model }) });
  }
  async selectModel(model: string): Promise<void> {
    if (this.live) await this.request('/api/models/select', { method: 'POST', body: JSON.stringify({ model }) });
    else mockModels.current = model;
  }
  async getConversations(): Promise<ConversationSummary[]> { return this.live ? this.request('/api/conversations') : mockConversations; }
  async createConversation(title = 'New conversation'): Promise<ConversationSummary> {
    const request: ConversationCreateRequest = { title };
    if (this.live) return this.request('/api/conversations', { method: 'POST', body: JSON.stringify(request) });
    const conversation = { id: crypto.randomUUID(), title };
    mockConversations.unshift(conversation);
    return conversation;
  }
  async getMessages(id: string): Promise<ConversationMessage[]> { return this.live ? this.request(`/api/conversations/${encodeURIComponent(id)}/messages`) : []; }
  async renameConversation(id: string, title: string): Promise<void> {
    await this.updateConversation(id, { title });
  }
  async updateConversation(id: string, patch: ConversationUpdate): Promise<void> {
    if (this.live) await this.request(`/api/conversations/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(patch) });
  }
  /** Delete this message and everything after it, so an edited version can be sent in its place. */
  async truncateConversation(id: string, fromMessageId: string): Promise<void> {
    await this.request(`/api/conversations/${encodeURIComponent(id)}/truncate`, { method: 'POST', body: JSON.stringify({ from_message_id: fromMessageId }) });
  }
  /** Copy the conversation up to and including this message into a new one. Files on disk are shared, not copied. */
  async forkConversation(id: string, throughMessageId: string, summarize = false): Promise<ConversationSummary> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/fork`, { method: 'POST', body: JSON.stringify({ through_message_id: throughMessageId, ...(summarize ? { summarize: true } : {}) }) });
  }
  async compactConversation(id: string): Promise<{ before_tokens: number | null; after_tokens: number | null; summary: string }> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/compact`, { method: 'POST' });
  }
  async getRunChanges(runId: string): Promise<RunChangeFile[]> {
    return (await this.request<{ files: RunChangeFile[] }>(`/api/runs/${encodeURIComponent(runId)}/changes`)).files;
  }
  async getWorkspaceTree(root: string, path = ''): Promise<WorkspaceEntry[]> {
    return (await this.request<{ entries: WorkspaceEntry[] }>(`/api/workspace/tree?${new URLSearchParams({ root, path })}`)).entries;
  }
  async getWorkspaceFile(root: string, path: string): Promise<WorkspaceFile> {
    return this.request(`/api/workspace/file?${new URLSearchParams({ root, path })}`);
  }
  async getWorkspaceRules(root: string): Promise<Array<{ path: string; bytes: number }>> {
    return (await this.request<{ files: Array<{ path: string; bytes: number }> }>(`/api/workspace/rules?${new URLSearchParams({ root })}`)).files;
  }
  async getProcesses(): Promise<ProcessInfo[]> { return this.live ? this.request('/api/processes') : []; }
  async getProcessOutput(id: string, after = 0): Promise<{ output: string; next: number; status: string }> {
    return this.request(`/api/processes/${encodeURIComponent(id)}/output?after=${after}`);
  }
  async killProcess(id: string): Promise<void> {
    await this.request(`/api/processes/${encodeURIComponent(id)}/kill`, { method: 'POST' });
  }
  async duplicateConversation(id: string): Promise<ConversationSummary> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/duplicate`, { method: 'POST' });
  }
  async searchWorkspace(root: string, q: string, limit = 20): Promise<Array<{ path: string; name: string; type: string }>> {
    return (await this.request<{ files: Array<{ path: string; name: string; type: string }> }>(`/api/workspace/search?${new URLSearchParams({ root, q, limit: String(limit) })}`)).files;
  }
  /** URL that streams a workspace file with its real content type (HTML is sandboxed by the backend). */
  rawFileUrl(root: string, path: string): string {
    return `${this.baseUrl}/api/workspace/raw?${new URLSearchParams({ root, path })}`;
  }
  async getBranches(root: string): Promise<{ current: string; branches: string[] }> {
    return this.request(`/api/git/branches?${new URLSearchParams({ root })}`);
  }
  async getWorktree(conversationId: string): Promise<WorktreeInfo> {
    return this.request(`/api/conversations/${encodeURIComponent(conversationId)}/worktree`);
  }
  async mergeWorktree(conversationId: string, strategy: 'merge' | 'squash', message?: string): Promise<unknown> {
    return this.request(`/api/conversations/${encodeURIComponent(conversationId)}/worktree/merge`, { method: 'POST', body: JSON.stringify({ strategy, ...(message ? { message } : {}) }) });
  }
  async removeWorktree(conversationId: string, options: { force?: boolean; keepBranch?: boolean } = {}): Promise<void> {
    const query = new URLSearchParams({ ...(options.force ? { force: 'true' } : {}), ...(options.keepBranch ? { keep_branch: 'true' } : {}) });
    await this.request(`/api/conversations/${encodeURIComponent(conversationId)}/worktree${query.size ? `?${query}` : ''}`, { method: 'DELETE' });
  }
  async getProfiles(): Promise<AgentProfile[]> { return this.live ? (await this.request<{ profiles: AgentProfile[] }>('/api/profiles')).profiles : []; }
  async saveProfile(profile: Partial<AgentProfile> & { name: string }): Promise<AgentProfile> {
    const { id, ...fields } = profile;
    return id ? this.request(`/api/profiles/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(fields) })
      : this.request('/api/profiles', { method: 'POST', body: JSON.stringify(fields) });
  }
  async deleteProfile(id: string): Promise<void> { await this.request(`/api/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async getRecipes(): Promise<Recipe[]> { return this.live ? (await this.request<{ recipes: Recipe[] }>('/api/recipes')).recipes : []; }
  async deleteRecipe(id: string): Promise<void> { await this.request(`/api/recipes/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async recipeFromRun(runId: string, name: string): Promise<Recipe> {
    return this.request('/api/recipes/from-run', { method: 'POST', body: JSON.stringify({ run_id: runId, name }) });
  }
  async renderRecipe(id: string, params: Record<string, string>): Promise<{ prompt: string; active_skills?: string[]; mode?: 'act' | 'plan'; workspace?: string | null; profile_id?: string | null }> {
    return this.request(`/api/recipes/${encodeURIComponent(id)}/render`, { method: 'POST', body: JSON.stringify({ params }) });
  }
  async cancelSubtask(runId: string, subtaskId: string): Promise<void> {
    await this.request(`/api/runs/${encodeURIComponent(runId)}/subtasks/${encodeURIComponent(subtaskId)}/cancel`, { method: 'POST' });
  }
  async updateGoal(id: string, patch: Record<string, unknown>): Promise<unknown> {
    return this.request(`/api/goals/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(patch) });
  }
  async setGoalPaused(id: string, paused: boolean): Promise<unknown> {
    return this.request(`/api/goals/${encodeURIComponent(id)}/${paused ? 'pause' : 'resume'}`, { method: 'POST' });
  }
  async getSshHosts(): Promise<Array<{ alias: string; hostname?: string; user?: string }>> {
    return this.live ? (await this.request<{ hosts: Array<{ alias: string; hostname?: string; user?: string }> }>('/api/ssh/hosts')).hosts : [];
  }
  async testSsh(host: string): Promise<{ ok: boolean; os: string | null; detail: string }> {
    return this.request('/api/ssh/test', { method: 'POST', body: JSON.stringify({ host }) });
  }
  async getPullRequest(root: string): Promise<PullRequestInfo | null> {
    return (await this.request<{ pr: PullRequestInfo | null }>(`/api/git/pr?${new URLSearchParams({ root })}`)).pr;
  }
  async createPullRequest(root: string, title: string, body: string, draft = false): Promise<PullRequestInfo> {
    const result = await this.request<{ pr?: PullRequestInfo } & Partial<PullRequestInfo>>('/api/git/pr', { method: 'POST', body: JSON.stringify({ root, title, body, draft }) });
    return (result.pr ?? result) as PullRequestInfo;
  }
  async getCheckLog(root: string, checkName: string): Promise<string> {
    const result = await this.request<{ log?: string; text?: string } | string>(`/api/git/pr/checks/${encodeURIComponent(checkName)}/log?${new URLSearchParams({ root })}`);
    return typeof result === 'string' ? result : result.log ?? result.text ?? '';
  }
  async getHooks(): Promise<HookConfig[]> { return this.live ? (await this.request<{ hooks: HookConfig[] }>('/api/hooks')).hooks : []; }
  async saveHook(hook: HookConfig, isNew: boolean): Promise<HookConfig> {
    return isNew ? this.request('/api/hooks', { method: 'POST', body: JSON.stringify(hook) })
      : this.request(`/api/hooks/${encodeURIComponent(hook.id)}`, { method: 'PUT', body: JSON.stringify(hook) });
  }
  async deleteHook(id: string): Promise<void> { await this.request(`/api/hooks/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async testHook(id: string): Promise<{ exit_code?: number; output?: string; duration_ms?: number }> {
    return this.request(`/api/hooks/${encodeURIComponent(id)}/test`, { method: 'POST' });
  }
  /** WebSocket URL for an interactive PowerShell in `cwd`. */
  terminalUrl(cwd: string): string {
    return `${this.baseUrl.replace(/^http/, 'ws')}/ws/terminal?${new URLSearchParams({ cwd })}`;
  }
  async deleteConversation(id: string): Promise<void> {
    if (this.live) await this.request(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }
  async getTools(): Promise<ToolListResponse> { return this.live ? this.request('/api/tools') : mockTools; }
  async getSkills(): Promise<SkillInfo[]> { return this.live ? (await this.request<{ skills: SkillInfo[] }>('/api/skills')).skills : []; }
  async getAgentCapabilities(): Promise<AgentCapabilityInfo[]> { return this.live ? (await this.request<{ capabilities: AgentCapabilityInfo[] }>('/api/agent/capabilities')).capabilities : []; }
  async getFacts(): Promise<Fact[]> { return this.live ? this.request('/api/facts') : []; }
  async saveFact(fact: Pick<Fact, 'key' | 'value' | 'category'>): Promise<void> {
    if (this.live) await this.request('/api/facts', { method: 'POST', body: JSON.stringify(fact) });
  }
  async deleteFact(key: string): Promise<void> {
    if (this.live) await this.request(`/api/facts/${encodeURIComponent(key)}`, { method: 'DELETE' });
  }
  async search(query: string): Promise<unknown[]> {
    return this.live ? this.request(`/api/search?q=${encodeURIComponent(query)}`) : [];
  }

  // -- Knowledge Base -------------------------------------------------------

  async getKnowledge(category?: string, limit = 50): Promise<KnowledgeEntry[]> {
    if (!this.live) return [];
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    params.set('limit', String(limit));
    return this.request(`/api/knowledge?${params}`);
  }

  async addKnowledge(entry: Pick<KnowledgeEntry, 'content' | 'source' | 'category'> & { metadata?: Record<string, unknown> }): Promise<KnowledgeEntry> {
    if (!this.live) return { id: crypto.randomUUID(), content: entry.content, source: entry.source ?? '', category: entry.category ?? 'general' };
    return this.request('/api/knowledge', { method: 'POST', body: JSON.stringify(entry) });
  }

  async searchKnowledge(query: string, category?: string, limit = 10): Promise<KnowledgeEntry[]> {
    if (!this.live) return [];
    const params = new URLSearchParams({ q: query });
    if (category) params.set('category', category);
    params.set('limit', String(limit));
    return this.request(`/api/knowledge/search?${params}`);
  }

  async deleteKnowledge(id: string): Promise<void> {
    if (this.live) await this.request(`/api/knowledge/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  // -- MCP Server Management ------------------------------------------------

  async getMCPServers(): Promise<MCPServerListResponse> {
    if (!this.live) return { servers: [] };
    return this.request('/api/mcp/servers');
  }

  async addMCPServer(req: MCPServerAddRequest): Promise<MCPServerInfo> {
    return this.request('/api/mcp/servers', { method: 'POST', body: JSON.stringify(req) });
  }

  async removeMCPServer(name: string): Promise<void> {
    if (this.live) await this.request(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' });
  }

  async restartMCPServer(name: string): Promise<MCPServerInfo> {
    return this.request(`/api/mcp/servers/${encodeURIComponent(name)}/restart`, { method: 'POST' });
  }

  async startRun(request: RunStartRequest, onEvent: (event: RuntimeStreamEvent) => void, shouldPause: () => boolean = () => false, maxReconnectAttempts = 5): Promise<void> {
    if (this.activeRuns.has(request.run_id)) throw new Error(`Run ${request.run_id} is already active`);
    this.activeRuns.add(request.run_id);
    try {
      await this.startRunInternal(request, onEvent, shouldPause, maxReconnectAttempts);
    } finally {
      this.activeRuns.delete(request.run_id);
    }
  }

  private async startRunInternal(request: RunStartRequest, onEvent: (event: RuntimeStreamEvent) => void, shouldPause: () => boolean, maxReconnectAttempts: number): Promise<void> {
    if (!this.live) {
      this.mockCancelled.delete(request.run_id);
      try {
        await streamMockRun(request, onEvent, shouldPause, () => this.mockCancelled.has(request.run_id), (eventId) => new Promise((resolve) => this.approvalResolvers.set(eventId, { runId: request.run_id, resolve })), (send) => this.mockControls.set(request.run_id, send));
      } finally {
        this.mockControls.delete(request.run_id);
        this.mockCancelled.delete(request.run_id);
        for (const [eventId, pending] of this.approvalResolvers) if (pending.runId === request.run_id) this.approvalResolvers.delete(eventId);
      }
      return;
    }

    const supportsReplay = await this.supportsRuntimeProtocol();
    if (!supportsReplay) throw new Error('Backend Agent Runtime 1.2 is required for event runs and approvals');
    const cursorKey = `atlas.runtime.cursor.${request.run_id}`;
    let lastSequence = Number(localStorage.getItem(cursorKey) ?? 0) || 0;
    let retries = 0;
    let terminal = false;
    const connect = (resume: boolean): Promise<void> => new Promise((resolve, reject) => {
      const path = '/ws/chat';
      const socket = new WebSocket(`${this.baseUrl.replace(/^http/, 'ws')}${path}`);
      this.runSockets.set(request.run_id, socket);
      let opened = false;
      let settled = false;
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        if (this.runSockets.get(request.run_id) === socket) this.runSockets.delete(request.run_id);
        if (error) reject(error); else resolve();
      };
      socket.addEventListener('open', () => {
        opened = true;
        const wireRequest: RunStartRequest | ResumeRequest = resume
          ? { type: 'resume', run_id: request.run_id, after_sequence: lastSequence }
          : request;
        socket.send(JSON.stringify(wireRequest));
      }, { once: true });
      socket.addEventListener('message', (message) => {
        let event: RuntimeStreamEvent;
        try { event = JSON.parse(String(message.data)) as RuntimeStreamEvent; } catch { return; }
        if ('type' in event && event.type === 'agent_event') {
          const runtimeEvent = event as RuntimeEventEnvelope;
          if (runtimeEvent.run_id !== request.run_id || !Number.isInteger(runtimeEvent.sequence) || runtimeEvent.sequence <= lastSequence) return;
          lastSequence = runtimeEvent.sequence;
          localStorage.setItem(cursorKey, String(lastSequence));
          onEvent(runtimeEvent);
          if (['run.completed', 'run.failed', 'run.cancelled'].includes(runtimeEvent.event)) {
            terminal = true; socket.close(1000, 'Run complete'); finish();
          }
          return;
        }
        return;
      });
      socket.addEventListener('error', () => {
        if (!opened) finish(new Error('WebSocket connection failed'));
      });
      socket.addEventListener('close', () => {
        if (this.runSockets.get(request.run_id) === socket) this.runSockets.delete(request.run_id);
        if (settled) return;
        if (terminal || this.mockCancelled.has(request.run_id)) { finish(); return; }
        if (!opened) { finish(new Error('WebSocket closed before the run started')); return; }
        if (!supportsReplay) { finish(new Error('Connection lost; this backend does not support run event replay')); return; }
        if (retries >= maxReconnectAttempts) { finish(new Error('Run disconnected; reconnect limit reached')); return; }
        retries += 1;
        window.setTimeout(() => { void connect(true).then(() => finish(), (error: Error) => {
          if (retries < maxReconnectAttempts && !terminal && !this.mockCancelled.has(request.run_id)) {
            window.setTimeout(() => { void connect(true).then(() => finish(), finish); }, Math.min(1000 * 2 ** (retries - 1), 8000));
          } else finish(error);
        }); }, Math.min(1000 * 2 ** (retries - 1), 8000));
      }, { once: true });
    });
    try { await connect(lastSequence > 0); }
    catch (error) {
      const message = error instanceof Error ? error.message : 'Backend run connection failed';
      this.availabilityError = message;
      if (/WebSocket|Connection lost|Run disconnected/.test(message)) this.live = false;
      throw error;
    }
    finally {
      if (terminal) localStorage.removeItem(cursorKey);
      this.mockControls.delete(request.run_id);
    }
  }

  respondToApproval(runId: string, response: ApprovalResponse): void {
    const pending = this.approvalResolvers.get(response.event_id);
    if (pending) {
      this.approvalResolvers.delete(response.event_id);
      pending.resolve(response.choice);
      return;
    }
    const socket = this.runSockets.get(runId);
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error('Agent Runtime socket is not connected');
    socket.send(JSON.stringify(response));
  }

  /** Send a client message on the socket of a live run (protocol 1.3 steer, input and plan replies). */
  private sendOnRun(runId: string, message: Record<string, unknown>): void {
    const socket = this.runSockets.get(runId);
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error('Agent Runtime socket is not connected');
    socket.send(JSON.stringify(message));
  }

  /** Add an instruction to a running run; it reaches the model before its next turn. */
  steerRun(runId: string, content: string, eventId: string): void {
    this.sendOnRun(runId, { type: 'run.steer', run_id: runId, content, event_id: eventId });
  }

  respondToInput(runId: string, eventId: string, text: string): void {
    this.sendOnRun(runId, { type: 'input.response', event_id: eventId, text });
  }

  /** Answer rules.trust_required: whether this directory's AGENTS.md etc. may be loaded. */
  trustRules(runId: string, eventId: string, trust: boolean): void {
    this.sendOnRun(runId, { type: 'rules.trust', run_id: runId, event_id: eventId, trust });
  }

  approvePlan(runId: string, eventId: string, edits = ''): void {
    this.sendOnRun(runId, { type: 'run.plan.approve', run_id: runId, event_id: eventId, edits });
  }

  cancelRun(runId: string): void {
    this.mockCancelled.add(runId);
    if (!this.live) {
      for (const [eventId, pending] of this.approvalResolvers) {
        if (pending.runId === runId) { this.approvalResolvers.delete(eventId); pending.resolve('deny'); }
      }
      return;
    }
    const socket = this.runSockets.get(runId);
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'run.cancel', run_id: runId }));
    }
  }

  controlRun(runId: string, type: 'run.pause' | 'run.resume'): void {
    if (!this.live) {
      this.mockControls.get(runId)?.(type === 'run.pause' ? 'run.paused' : 'run.resumed');
      return;
    }
    if (!this.hasEventProtocol()) throw new Error('This backend does not support Agent Run controls');
    const socket = this.runSockets.get(runId);
    if (socket?.readyState !== WebSocket.OPEN) throw new Error('Agent Runtime socket is not connected');
    socket.send(JSON.stringify({ type, run_id: runId }));
  }
}
