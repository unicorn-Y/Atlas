import { mockConversations, mockModels, mockProviders, mockReasoningStages, mockTools, streamMockRun } from './mock';
import type { UsageGroup, UsageReport, AgentCapabilityInfo, ApprovalResponse, ConfigurationResponse, ConnectionTestResponse, ConversationCreateRequest, ConversationMessage, ConversationSummary, ConversationUpdate, CustomModelRequest, CustomModelUpdateRequest, CustomTool, CustomCommandInfo, CommandRenderResult, ExternalAgentInfo, ExternalImportScan, ExternalImportResult, Fact, InitApplyResult, InitProposal, KeySlotInfo, LspStatus, ModelInfo, ModelTestResponse, ProjectSource, ProjectSources, ProviderState, ReasoningStagesConfig, RewindResult, RunDiagnostics, SandboxStatus, TelegramSettings, WorkspaceVersion, KnowledgeEntry, MCPServerAddRequest, MCPServerInfo, MCPServerListResponse, ModelListResponse, AgentProfile, HookConfig, HookLog, MarketplaceInfo, MarketplacePluginEntry, PluginActionResult, PluginInfo, ProcessInfo, PullRequestInfo, Recipe, ResumeRequest, WorktreeInfo, RunChangeFile, RunStartRequest, RuntimeEventEnvelope, RuntimeStreamEvent, SkillInfo, ToolListResponse, WorkspaceEntry, WorkspaceFile } from './types';

export interface BackendAdapterOptions {
  baseUrl: string;
}

/**
 * 后端调用失败。`message` 是给用户看的主文案（中文白话）；`detail` 保留原始英文报错，
 * 由界面收进「详细信息」里展开，不直接糊在错误横幅上。
 */
export class BackendError extends Error {
  readonly detail?: string;
  constructor(message: string, detail?: string) {
    super(message);
    this.name = 'BackendError';
    this.detail = detail;
  }
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
      this.availabilityError = response.ok ? null : `Atlas 后端没有响应（HTTP ${response.status}）`;
    } catch {
      this.live = false;
      this.availabilityError = '连不上 Atlas 后端，请确认它已经启动';
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
    } catch {
      this.live = false;
      this.availabilityError = '连不上 Atlas 后端，请确认它已经启动';
      throw new BackendError('连不上 Atlas 后端，请确认它已经启动', 'network request failed');
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string };
      const detail = typeof body.detail === 'string' && body.detail ? body.detail : undefined;
      // 后端给了 detail 就直接用它（后端消息多为中文）；否则用中文兜底，原始英文留在 detail。
      const message = detail ?? `后端请求失败（HTTP ${response.status}）`;
      if (response.status >= 500) {
        this.live = false;
        this.availabilityError = message;
      }
      throw new BackendError(message, detail ? undefined : `Backend request failed (${response.status})`);
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
    return { ...mockModels, gateway_base_url: this.baseUrl, api_key_configured: false, compression_model: '' };
  }
  async updateConfiguration(gatewayBaseUrl: string, apiKey: string, compressionModel?: string): Promise<ConfigurationResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存 API 配置');
    return this.request('/api/settings/configuration', { method: 'PUT', body: JSON.stringify({ gateway_base_url: gatewayBaseUrl, api_key: apiKey || null, ...(compressionModel !== undefined ? { compression_model: compressionModel } : {}) }) });
  }
  async updateSubagentSettings(enabled: boolean, defaultModel: string): Promise<ConfigurationResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存子 Agent 设置');
    return this.request('/api/settings/configuration', { method: 'PUT', body: JSON.stringify({ subagents_enabled: enabled, subagent_default_model: defaultModel }) });
  }
  async addCustomModel(model: CustomModelRequest): Promise<ConfigurationResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存自定义模型');
    return this.request('/api/models/custom', { method: 'POST', body: JSON.stringify(model) });
  }

  // -- Provider catalog, provider keys and reasoning stages (C5) ------------

  async getProviders(): Promise<ProviderState[]> { return this.live ? this.request('/api/providers') : mockProviders; }
  async updateProviderConfig(providerId: string, baseUrl: string | null): Promise<void> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存服务商设置');
    await this.request(`/api/providers/${encodeURIComponent(providerId)}/config`, { method: 'PUT', body: JSON.stringify({ base_url: baseUrl }) });
  }
  async addProviderKey(providerId: string, secret: string, label?: string): Promise<{ id: string; label?: string }> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存服务商密钥');
    return this.request(`/api/providers/${encodeURIComponent(providerId)}/keys`, { method: 'POST', body: JSON.stringify({ secret, ...(label ? { label } : {}) }) });
  }
  async listProviderKeys(providerId: string): Promise<KeySlotInfo[]> {
    if (!this.live) return mockProviders.find((provider) => provider.id === providerId)?.keys ?? [];
    return (await this.request<{ keys: KeySlotInfo[] }>(`/api/providers/${encodeURIComponent(providerId)}/keys`)).keys;
  }
  async removeProviderKey(providerId: string, keyId: string): Promise<void> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能删除服务商密钥');
    await this.request(`/api/providers/${encodeURIComponent(providerId)}/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
  }
  async updateCustomModel(modelId: string, patch: CustomModelUpdateRequest): Promise<ModelInfo> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能修改自定义模型');
    return this.request(`/api/models/custom/${encodeURIComponent(modelId)}`, { method: 'PUT', body: JSON.stringify(patch) });
  }
  async deleteCustomModel(modelId: string): Promise<void> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能删除自定义模型');
    await this.request(`/api/models/custom/${encodeURIComponent(modelId)}`, { method: 'DELETE' });
  }
  async getReasoningStages(): Promise<ReasoningStagesConfig> {
    return this.live ? this.request('/api/models/reasoning-stages') : { ...mockReasoningStages };
  }
  async saveReasoningStages(config: ReasoningStagesConfig): Promise<ReasoningStagesConfig> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能保存思考量分配');
    return this.request('/api/models/reasoning-stages', { method: 'PUT', body: JSON.stringify(config) });
  }
  async testModelById(modelId: string): Promise<ModelTestResponse> {
    if (!this.live) throw new Error('连接 Atlas 后端后才能测试模型连接');
    return this.request('/api/models/test', { method: 'POST', body: JSON.stringify({ model_id: modelId }) });
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
  async createConversation(title = '新对话'): Promise<ConversationSummary> {
    const request: ConversationCreateRequest = { title };
    if (this.live) return this.request('/api/conversations', { method: 'POST', body: JSON.stringify(request) });
    const conversation = { id: crypto.randomUUID(), title };
    mockConversations.unshift(conversation);
    return conversation;
  }
  /**
   * 消息历史，一页。limit 返回最新的那么多条（后端默认 100、上限 1000），升序输出；
   * beforeId 取这条消息之前的更早一页（同样升序），供向上翻页使用。
   */
  async getMessages(id: string, opts?: { limit?: number; beforeId?: string }): Promise<ConversationMessage[]> {
    if (!this.live) return [];
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set('limit', String(opts.limit));
    if (opts?.beforeId) params.set('before_id', String(opts.beforeId));
    const query = params.toString();
    return this.request(`/api/conversations/${encodeURIComponent(id)}/messages${query ? `?${query}` : ''}`);
  }
  async getConversationBranches(id: string): Promise<Array<{ id: string; parent_session_id?: string | null; title: string; branch_message_id?: string | null }>> {
    return this.live ? this.request(`/api/conversations/${encodeURIComponent(id)}/branches`) : [];
  }
  async getConversationGoal(id: string): Promise<{ output: string; goal: { text: string; status: string; turns_used: number; max_turns: number; subgoals: unknown[] } | null }> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/goal`);
  }
  async runConversationGoalCommand(id: string, command: string): Promise<{ output: string; prompt?: string | null; kickoff?: boolean; goal: { text: string; status: string; turns_used: number; max_turns: number; subgoals: unknown[] } | null }> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/goal`, { method: 'POST', body: JSON.stringify({ command }) });
  }
  async summarizeConversationBranch(id: string): Promise<{ created: boolean; reason?: string; summary?: string }> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/branch-summary`, { method: 'POST' });
  }
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
  async compactConversation(id: string, note = ''): Promise<{ before_tokens: number | null; after_tokens: number | null; summary: string }> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/compact`, {
      method: 'POST', body: JSON.stringify(note.trim() ? { focus_topic: note.trim() } : {}),
    });
  }
  async getRunChanges(runId: string): Promise<RunChangeFile[]> {
    return (await this.request<{ files: RunChangeFile[] }>(`/api/runs/${encodeURIComponent(runId)}/changes`)).files;
  }

  // -- C6: /init 提案、LSP 诊断与服务状态 ------------------------------------

  /** 只读扫描工作区并生成 AGENTS.md 提案（含 unified diff），不落盘。 */
  async initPreview(workspace: string): Promise<InitProposal> {
    return this.request('/api/init/preview', { method: 'POST', body: JSON.stringify({ workspace }) });
  }
  /**
   * 写入 AGENTS.md。冲突检测契约：`expectedExisting` 必须是预览时读到的旧内容——
   * 文件不存在时必须传 null，存在时原样回传 existing_content；磁盘内容一旦对不上，后端以 422 拒绝。
   */
  async initApply(workspace: string, content: string, expectedExisting: string | null): Promise<InitApplyResult> {
    return this.request('/api/init/apply', { method: 'POST', body: JSON.stringify({ workspace, content, expected_existing: expectedExisting }) });
  }
  /** 这次运行改过的文件当前的 LSP 诊断（全新快照，非增量）。 */
  async getRunDiagnostics(runId: string): Promise<RunDiagnostics> {
    return this.request(`/api/runs/${encodeURIComponent(runId)}/diagnostics`);
  }
  /** 逐个探测本机的语言服务是否可用；`hint` 说明缺了什么。 */
  async getLspStatus(workspace: string): Promise<LspStatus> {
    return this.request(`/api/lsp/status?${new URLSearchParams({ workspace })}`);
  }

  async getWorkspaceTree(root: string, path = ''): Promise<WorkspaceEntry[]> {
    return (await this.request<{ entries: WorkspaceEntry[] }>(`/api/workspace/tree?${new URLSearchParams({ root, path })}`)).entries;
  }
  async getWorkspaceFile(root: string, path: string): Promise<WorkspaceFile> {
    return this.request(`/api/workspace/file?${new URLSearchParams({ root, path })}`);
  }
  async saveWorkspaceFile(root: string, path: string, content: string, expectedSha256: string): Promise<{ path: string; sha256: string }> {
    return this.request(`/api/workspace/file?${new URLSearchParams({ root, path })}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, expected_sha256: expectedSha256 }),
    });
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
  async getExternalAgents(): Promise<ExternalAgentInfo[]> {
    return this.live ? (await this.request<{ agents: ExternalAgentInfo[] }>('/api/agents/external')).agents : [];
  }
  async getSandboxStatus(): Promise<SandboxStatus> {
    return this.live ? this.request('/api/sandbox/status') : { docker: { available: false, version: null, detail: '' } };
  }
  /** Static HTML rendering of a .docx / .xlsx / .pptx, served sandboxed with no scripts. */
  officePreviewUrl(root: string, path: string): string {
    return `${this.baseUrl}/api/workspace/preview?${new URLSearchParams({ root, path })}`;
  }
  async getFileHistory(root: string, path: string): Promise<WorkspaceVersion[]> {
    return (await this.request<{ versions: WorkspaceVersion[] }>(`/api/workspace/history?${new URLSearchParams({ root, path })}`)).versions;
  }
  async getVersionContent(root: string, path: string, version: string): Promise<WorkspaceFile> {
    return this.request(`/api/workspace/history/content?${new URLSearchParams({ root, path, version })}`);
  }
  async restoreVersion(root: string, path: string, version: string): Promise<{ restored: boolean; checkpoint_id: string }> {
    return this.request('/api/workspace/history/restore', { method: 'POST', body: JSON.stringify({ root, path, version }) });
  }
  /** Remove a message and everything after it; `files` also puts back what those runs changed. */
  async rewindConversation(id: string, messageId: string, files: boolean): Promise<RewindResult> {
    return this.request(`/api/conversations/${encodeURIComponent(id)}/rewind`, { method: 'POST', body: JSON.stringify({ message_id: messageId, files }) });
  }
  async redoRewind(id: string, rewindId: string): Promise<void> {
    await this.request(`/api/conversations/${encodeURIComponent(id)}/rewind/${encodeURIComponent(rewindId)}/redo`, { method: 'POST', body: '{}' });
  }
  async getCustomTools(): Promise<CustomTool[]> { return this.live ? (await this.request<{ tools: CustomTool[] }>('/api/custom-tools')).tools : []; }
  async saveCustomTool(tool: CustomTool & { script_name?: string; script?: string }, isNew: boolean): Promise<CustomTool> {
    return isNew ? this.request('/api/custom-tools', { method: 'POST', body: JSON.stringify(tool) })
      : this.request(`/api/custom-tools/${encodeURIComponent(tool.id)}`, { method: 'PUT', body: JSON.stringify(tool) });
  }
  async deleteCustomTool(id: string): Promise<void> { await this.request(`/api/custom-tools/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async testCustomTool(id: string, args: Record<string, unknown>): Promise<{ result?: unknown; stderr?: string; exit_code?: number; is_error?: boolean; error?: string; truncated?: boolean }> {
    return this.request(`/api/custom-tools/${encodeURIComponent(id)}/test`, { method: 'POST', body: JSON.stringify({ arguments: args }) });
  }
  /** Token usage and estimated cost from the backend ledger; `from` / `to` are ISO dates (to is exclusive). */
  async getUsage(groupBy: UsageGroup, from?: string, to?: string): Promise<UsageReport> {
    const empty: UsageReport = { rows: [], totals: { runs: 0, input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, cache_hit_rate: null, est_cost: 0 } };
    if (!this.live) return empty;
    const query = new URLSearchParams({ group_by: groupBy, ...(from ? { from } : {}), ...(to ? { to } : {}) });
    return this.request(`/api/usage?${query}`);
  }
  async getTelegram(): Promise<TelegramSettings> { return this.request('/api/channels/telegram'); }
  async saveTelegram(patch: Partial<Omit<TelegramSettings, 'bot_token_set'>> & { bot_token?: string }): Promise<TelegramSettings> {
    return this.request('/api/channels/telegram', { method: 'PUT', body: JSON.stringify(patch) });
  }
  async testTelegram(): Promise<{ username: string }> { return this.request('/api/channels/telegram/test', { method: 'POST', body: '{}' }); }
  async getProjectSources(projectId: string): Promise<ProjectSources> { return this.request(`/api/projects/${encodeURIComponent(projectId)}/sources`); }
  async setProjectInstructions(projectId: string, instructions: string): Promise<void> {
    await this.request(`/api/projects/${encodeURIComponent(projectId)}/sources/instructions`, { method: 'PUT', body: JSON.stringify({ instructions }) });
  }
  async addProjectSource(projectId: string, source: { kind: ProjectSource['kind']; title?: string; path?: string; url?: string; text?: string }): Promise<ProjectSource> {
    return this.request(`/api/projects/${encodeURIComponent(projectId)}/sources`, { method: 'POST', body: JSON.stringify(source) });
  }
  async deleteProjectSource(projectId: string, sourceId: string): Promise<void> {
    await this.request(`/api/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
  }
  async refreshProjectSource(projectId: string, sourceId: string): Promise<void> {
    await this.request(`/api/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/refresh`, { method: 'POST', body: '{}' });
  }
  async getHooks(workspace?: string): Promise<{ hooks: HookConfig[]; logs: HookLog[] }> {
    if (!this.live) return { hooks: [], logs: [] };
    const query = workspace ? `?${new URLSearchParams({ workspace })}` : '';
    return this.request<{ hooks: HookConfig[]; logs: HookLog[] }>(`/api/hooks${query}`);
  }
  async saveHook(hook: HookConfig, isNew: boolean): Promise<HookConfig> {
    return isNew ? this.request('/api/hooks', { method: 'POST', body: JSON.stringify(hook) })
      : this.request(`/api/hooks/${encodeURIComponent(hook.id)}`, { method: 'PUT', body: JSON.stringify(hook) });
  }
  /** Works for Atlas hooks and read-only Claude/plugin hook groups; the choice is stored as an override. */
  async setHookEnabled(id: string, enabled: boolean, workspace?: string): Promise<HookConfig> {
    return this.request(`/api/hooks/${encodeURIComponent(id)}/enabled`, { method: 'POST', body: JSON.stringify({ enabled, ...(workspace ? { workspace } : {}) }) });
  }
  async deleteHook(id: string): Promise<void> { await this.request(`/api/hooks/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async testHook(id: string, workspace?: string): Promise<HookLog> {
    const query = workspace ? `?${new URLSearchParams({ workspace })}` : '';
    return this.request(`/api/hooks/${encodeURIComponent(id)}/test${query}`, { method: 'POST' });
  }

  // -- Plugins & marketplaces ----------------------------------------------

  async getPlugins(): Promise<PluginInfo[]> { return this.live ? (await this.request<{ plugins: PluginInfo[] }>('/api/plugins')).plugins : []; }
  /** Install from a local directory that holds plugin components (plugin.json etc.). */
  async installPluginLocal(path: string): Promise<PluginActionResult> {
    return this.request('/api/plugins/install-local', { method: 'POST', body: JSON.stringify({ path }) });
  }
  /** Install from a local directory, git URL or `owner/repo`; a marketplace source registers the marketplace. */
  async installPlugin(source: string, name?: string, ref?: string): Promise<PluginActionResult> {
    return this.request('/api/plugins/install', { method: 'POST', body: JSON.stringify({ source, ...(name ? { name } : {}), ...(ref ? { ref } : {}) }) });
  }
  async updatePlugin(name: string): Promise<PluginActionResult> {
    return this.request(`/api/plugins/${encodeURIComponent(name)}/update`, { method: 'POST' });
  }
  async uninstallPlugin(name: string): Promise<PluginActionResult> {
    return this.request(`/api/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' });
  }
  async setPluginEnabled(name: string, enabled: boolean): Promise<PluginActionResult> {
    return this.request(`/api/plugins/${encodeURIComponent(name)}/enabled`, { method: 'POST', body: JSON.stringify({ enabled }) });
  }
  async getMarketplaces(): Promise<MarketplaceInfo[]> {
    return this.live ? (await this.request<{ marketplaces: MarketplaceInfo[] }>('/api/plugin-marketplaces')).marketplaces : [];
  }
  async addMarketplace(source: string, name?: string, ref?: string): Promise<{ name: string; path: string; plugins: number }> {
    return this.request('/api/plugin-marketplaces', { method: 'POST', body: JSON.stringify({ source, ...(name ? { name } : {}), ...(ref ? { ref } : {}) }) });
  }
  async getMarketplacePlugins(name: string): Promise<MarketplacePluginEntry[]> {
    return (await this.request<{ plugins: MarketplacePluginEntry[] }>(`/api/plugin-marketplaces/${encodeURIComponent(name)}/plugins`)).plugins;
  }
  async installMarketplacePlugin(marketplace: string, plugin: string): Promise<PluginActionResult> {
    return this.request(`/api/plugin-marketplaces/${encodeURIComponent(marketplace)}/install`, { method: 'POST', body: JSON.stringify({ plugin }) });
  }

  // -- Custom commands & external import -----------------------------------

  /** User-defined commands (Markdown commands and exported recipes) for a workspace; omit for user-level only. */
  async getCommands(workspace?: string): Promise<CustomCommandInfo[]> {
    if (!this.live) return [];
    const query = workspace ? `?${new URLSearchParams({ workspace })}` : '';
    return (await this.request<{ commands: CustomCommandInfo[] }>(`/api/commands${query}`)).commands;
  }
  async renderCommand(id: string, args: string, workspace?: string): Promise<CommandRenderResult> {
    return this.request('/api/commands/render', { method: 'POST', body: JSON.stringify({ id, arguments: args, ...(workspace ? { workspace } : {}) }) });
  }
  /** Read-only scan of another agent's config; pass `source: 'claude' | 'codex'`. */
  async scanExternalImport(source: string, workspace?: string): Promise<ExternalImportScan> {
    const query = new URLSearchParams({ source, ...(workspace ? { workspace } : {}) });
    return this.request(`/api/import/external/scan?${query}`);
  }
  /** `items` are the scanned items the user approved; source directories are never modified. */
  async importExternal(source: string, items: ExternalImportScan['items'], workspace?: string): Promise<ExternalImportResult> {
    return this.request('/api/import/external', { method: 'POST', body: JSON.stringify({ source, items, ...(workspace ? { workspace } : {}) }) });
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
    if (this.activeRuns.has(request.run_id)) throw new BackendError('这个任务已经在运行了，等它结束或先停止再发', `Run ${request.run_id} is already active`);
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
    if (!supportsReplay) throw new BackendError('这台电脑上的 Atlas 后端版本太旧，请把后端升级到 Agent Runtime 1.2 以上再试', 'Backend Agent Runtime 1.2 is required for event runs and approvals');
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
        if (!opened) finish(new BackendError('连不上后端的任务通道', 'WebSocket connection failed'));
      });
      socket.addEventListener('close', () => {
        if (this.runSockets.get(request.run_id) === socket) this.runSockets.delete(request.run_id);
        if (settled) return;
        if (terminal || this.mockCancelled.has(request.run_id)) { finish(); return; }
        if (!opened) { finish(new BackendError('任务还没开始，连接就断开了', 'WebSocket closed before the run started')); return; }
        if (!supportsReplay) { finish(new BackendError('连接中断，这个后端不支持断线续跑', 'Connection lost; this backend does not support run event replay')); return; }
        if (retries >= maxReconnectAttempts) { finish(new BackendError('连接断了好几次都没能恢复，这次任务中断了', 'Run disconnected; reconnect limit reached')); return; }
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
      // 英文原始报错留在 detail 里；这里用它判断连接类故障，主文案已是中文。
      const raw = error instanceof BackendError ? (error.detail ?? error.message) : error instanceof Error ? error.message : 'Backend run connection failed';
      this.availabilityError = error instanceof Error ? error.message : raw;
      if (/WebSocket|Connection lost|Run disconnected/.test(raw)) this.live = false;
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
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new BackendError('和后端的连接已断开，这条操作没能送达', 'Agent Runtime socket is not connected');
    socket.send(JSON.stringify(response));
  }

  /** Send a client message on the socket of a live run (protocol 1.3 steer, input and plan replies). */
  private sendOnRun(runId: string, message: Record<string, unknown>): void {
    const socket = this.runSockets.get(runId);
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new BackendError('和后端的连接已断开，这条操作没能送达', 'Agent Runtime socket is not connected');
    socket.send(JSON.stringify(message));
  }

  /** Add an instruction to a running run; it reaches the model before its next turn. */
  steerRun(runId: string, content: string, eventId: string, immediate = false): void {
    this.sendOnRun(runId, { type: 'run.steer', run_id: runId, content, event_id: eventId, immediate });
  }

  /** Add an instruction directly to a running delegated subtask. */
  steerSubtask(runId: string, subtaskId: string, text: string, eventId: string): void {
    this.sendOnRun(runId, { type: 'subtask.message', run_id: runId, subtask_id: subtaskId, text, event_id: eventId });
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
    if (!this.hasEventProtocol()) throw new BackendError('这个后端版本不支持暂停/继续，请升级 Atlas 后端', 'This backend does not support Agent Run controls');
    const socket = this.runSockets.get(runId);
    if (socket?.readyState !== WebSocket.OPEN) throw new BackendError('和后端的连接已断开，这条操作没能送达', 'Agent Runtime socket is not connected');
    socket.send(JSON.stringify({ type, run_id: runId }));
  }
}
