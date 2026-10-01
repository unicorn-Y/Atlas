import { create } from 'zustand';
import { BackendAdapter } from '@atlas/backend-adapter';
import type { AgentCapabilityInfo, AgentProfile, PermissionMode, ConfigurationResponse, ConversationMessage, ConversationSummary, ConversationUpdate, CustomModelRequest, ModelListResponse, ReasoningEffort, Recipe, RewindResult, RunFile, RuntimeEventEnvelope, SkillInfo, ToolListResponse } from '@atlas/backend-adapter';
import type { AgentEvent, AgentRun, AgentRunStatus } from '../../types/runtime';
import type { Artifact } from '../../types/artifact';
import { applyRuntimeEvent, isRuntimeEvent, normalizeRuntimeEvent } from '../services/runtimeEvents';

const desktopApiBaseUrl = typeof window === 'undefined' ? undefined : window.atlasDesktop?.apiBaseUrl;

/** Extra context picked in the composer: @files from the workspace and #conversations. */
export interface ContextRefs { files: string[]; conversations: string[] }
/** What the user sends: text, images (data URLs), other files, and referenced context. */
export interface Outgoing { content: string; attachments: string[]; files: RunFile[]; refs?: ContextRefs; /** One-off role for this message only. */ profileId?: string }
export interface QueuedMessage extends Outgoing { id: string }
/** How a message typed while a run is working is delivered: folded into the run now, or run afterwards. */
export type FollowUpMode = 'steer' | 'queue';

export const backend = new BackendAdapter({ baseUrl: desktopApiBaseUrl || import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8765' });

interface AtlasState {
  apiBaseUrl: string;
  providerBaseUrl: string;
  apiKeyConfigured: boolean;
  agentEngine: 'hermes' | 'legacy';
  compressionModel: string;
  /** The backend's model configuration has been read at least once (apiKeyConfigured is meaningful). */
  configLoaded: boolean;
  settingsBusy: boolean;
  connectionTest: { ok: boolean; message: string } | null;
  mode: 'mock' | 'backend';
  connected: boolean;
  busy: boolean;
  paused: boolean;
  error: string | null;
  model: string;
  models: ModelListResponse['models'];
  tools: ToolListResponse['tools'];
  skills: SkillInfo[];
  activeSkills: string[];
  capabilities: AgentCapabilityInfo[];
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  loadingMessagesConversationId: string | null;
  creatingConversation: boolean;
  conversationMessages: Record<string, ConversationMessage[]>;
  activeConversationId: string;
  runs: AgentRun[];
  activeRunId: string | null;
  artifacts: Artifact[];
  /** Follow-up messages waiting for their conversation's run to end; sent in order. */
  queue: Record<string, QueuedMessage[]>;
  /** A stopped run pauses its conversation's queue instead of starting the next message. */
  queuePaused: Record<string, boolean>;
  /** Steers sent to a run and not yet confirmed by run.steered; they fall back to the queue if the run ends first. */
  pendingSteers: Record<string, QueuedMessage[]>;
  followUpMode: FollowUpMode;
  /** Mode for the next message: `plan` explores read-only and waits for approval. Resets after sending. */
  nextRunMode: 'act' | 'plan';
  /** Answers given to Agent questions, by input event id. */
  answers: Record<string, string>;
  unread: string[];
  pinned: string[];
  archived: string[];
  runPrompts: Record<string, Outgoing>;
  profiles: AgentProfile[];
  recipes: Recipe[];
  /** Role for new runs; the backend applies its model, skills, tools and mode. */
  profileId: string;
  reasoningEffort: ReasoningEffort | '';
  /** Conversations whose next run should start in their own git worktree. */
  worktreeRequests: Record<string, { base_branch?: string }>;
  initialize: () => Promise<void>;
  openConversation: (conversation: ConversationSummary) => Promise<void>;
  createConversation: (title?: string) => Promise<void>;
  selectModel: (model: string) => Promise<void>;
  applySkill: (name: string) => void;
  removeSkill: (name: string) => void;
  saveProviderSettings: (baseUrl: string, apiKey: string) => Promise<boolean>;
  saveAgentEngine: (engine: 'hermes' | 'legacy') => Promise<boolean>;
  saveCompressionModel: (model: string) => Promise<boolean>;
  addCustomModel: (model: CustomModelRequest) => Promise<boolean>;
  testModelConnection: (model?: string) => Promise<void>;
  sendMessage: (content: string, attachments?: string[], files?: RunFile[], refs?: ContextRefs, profileId?: string) => Promise<void>;
  createRun: (conversationId: string, title: string) => AgentRun;
  appendEvent: (event: AgentEvent) => void;
  getRun: (runId: string) => AgentRun | undefined;
  setActiveRun: (runId: string | null) => void;
  removeRun: (runId: string) => void;
  approve: (eventId: string) => void;
  reject: (eventId: string) => void;
  answerInput: (runId: string, eventId: string, text: string) => void;
  approvePlan: (runId: string, eventId: string, edits?: string) => void;
  trustRules: (runId: string, eventId: string, trust: boolean) => void;
  /** Per-conversation permission mode for the next runs; the backend remembers the last one used. */
  setPermissionMode: (conversationId: string, mode: PermissionMode) => void;
  /** Workspace, permission, executor, sandbox, extra directories: applied now and saved on the conversation. */
  setConversationSettings: (conversationId: string, patch: Omit<ConversationUpdate, 'title' | 'pinned' | 'archived'>) => void;
  togglePaused: () => void;
  stopTask: () => void;
  stopRun: (runId: string) => void;
  dismissError: () => void;
  setFollowUpMode: (mode: FollowUpMode) => void;
  setNextRunMode: (mode: 'act' | 'plan') => void;
  removeQueued: (conversationId: string, id: string) => void;
  takeQueued: (conversationId: string, id: string) => QueuedMessage | undefined;
  sendQueuedNow: (conversationId: string, id: string) => void;
  steerQueued: (conversationId: string, id: string) => void;
  resumeQueue: (conversationId: string) => void;
  retryRun: (runId: string) => void;
  renameConversation: (id: string, title: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  togglePinned: (id: string) => void;
  toggleArchived: (id: string) => void;
  exportConversation: (id: string, format?: 'json' | 'md') => Promise<void>;
  setWorkspace: (conversationId: string, workspace: string | null) => void;
  editMessage: (messageId: string, content: string) => Promise<void>;
  /** Drop a message and everything after it; with `files`, also undo what those runs changed. Returns the rewind to redo. */
  rewindTo: (messageId: string, files: boolean) => Promise<RewindResult | null>;
  redoRewind: (conversationId: string, rewindId: string) => Promise<boolean>;
  forkFrom: (messageId: string, summarize?: boolean) => Promise<void>;
  compactConversation: (id: string, note?: string) => Promise<string | null>;
  setProfile: (id: string) => void;
  reloadProfiles: () => Promise<void>;
  setReasoningEffort: (effort: ReasoningEffort | '') => void;
  requestWorktree: (conversationId: string, baseBranch: string | null) => void;
  refreshConversations: () => Promise<void>;
  duplicateConversation: (id: string) => Promise<void>;
  cancelSubtask: (runId: string, subtaskId: string) => void;
  /** Extra instructions for a running sub-agent. */
  messageSubtask: (runId: string, subtaskId: string, text: string) => void;
  saveRecipe: (runId: string, name: string) => Promise<boolean>;
  deleteRecipe: (id: string) => Promise<void>;
  runRecipe: (id: string, params: Record<string, string>) => Promise<void>;
}

const terminal = new Set<AgentRunStatus>(['completed', 'failed', 'cancelled']);
const storageGet = (key: string) => { try { return localStorage.getItem(key); } catch { return null; } };
const storageSet = (key: string, value: string | null) => {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* storage unavailable */ }
};
const readList = (key: string): string[] => {
  try {
    const value: unknown = JSON.parse(storageGet(key) ?? '[]');
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
  } catch { return []; }
};
const ACTIVE_SKILLS = 'atlas.active-skills';
const PROFILE = 'atlas.preference.profile';
const REASONING = 'atlas.preference.reasoning';
const FOLLOW_UP = 'atlas.preference.follow-up';
// Pins and archives lived in localStorage before the backend stored them; migrated once on startup.
const LEGACY_PINNED = 'atlas.conversations.pinned';
const LEGACY_ARCHIVED = 'atlas.conversations.archived';

const flags = (conversations: ConversationSummary[]) => ({
  pinned: conversations.filter((item) => item.pinned && !item.archived).map((item) => item.id),
  archived: conversations.filter((item) => item.archived).map((item) => item.id),
});

/** Native desktop notification, only when Atlas is not what the user is looking at. */
function notifyDesktop(title: string, body: string, onClick: () => void) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  if (typeof document !== 'undefined' && document.hasFocus()) return;
  const notification = new Notification(title, { body, silent: false });
  notification.onclick = () => { window.focus(); onClick(); notification.close(); };
}
const RUN_OUTCOME: Record<string, string> = { 'run.completed': '已完成', 'run.failed': '出错了', 'run.cancelled': '已停止' };
const errorText = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback;

export const useAtlasStore = create<AtlasState>((set, get) => {
  /** Record a backend failure; network errors also flip the connection state. */
  const fail = (error: unknown, fallback: string) => set({ mode: backend.mode, connected: backend.mode === 'backend', error: errorText(error, fallback) });
  const patchConversation = (id: string, patch: Partial<ConversationSummary>) => set((state) => {
    const conversations = state.conversations.map((item) => item.id === id ? { ...item, ...patch } : item);
    return { conversations, ...flags(conversations) };
  });

  return {
    apiBaseUrl: backend.apiBaseUrl, providerBaseUrl: backend.apiBaseUrl, apiKeyConfigured: false, agentEngine: 'hermes', compressionModel: '', configLoaded: false, settingsBusy: false, connectionTest: null,
    mode: 'mock', connected: false, busy: false, paused: false, error: null,
    model: '', models: [], tools: [], conversations: [], conversationsLoading: false, loadingMessagesConversationId: null, creatingConversation: false, conversationMessages: {}, activeConversationId: '',
    runs: [], activeRunId: null, artifacts: [], skills: [], capabilities: [], activeSkills: readList(ACTIVE_SKILLS),
    queue: {}, queuePaused: {}, pendingSteers: {}, followUpMode: storageGet(FOLLOW_UP) === 'queue' ? 'queue' : 'steer', nextRunMode: 'act', answers: {},
    unread: [], pinned: [], archived: [], runPrompts: {},
    profiles: [], recipes: [], profileId: storageGet(PROFILE) ?? 'default',
    reasoningEffort: (['minimal', 'low', 'medium', 'high'].includes(storageGet(REASONING) ?? '') ? storageGet(REASONING) : '') as ReasoningEffort | '',
    worktreeRequests: {},

    initialize: async () => {
      set({ conversationsLoading: true });
      const mode = await backend.initialize();
      set({ mode, connected: mode === 'backend', error: mode === 'mock' ? backend.availabilityError : null });
      try {
        const [configuration, loaded, toolList, skills, capabilities] = await Promise.all([backend.getConfiguration(), backend.getConversations(), backend.getTools(), backend.getSkills(), backend.getAgentCapabilities()]);
        const conversations = await migrateLegacyFlags(loaded);
        const preferredModel = storageGet('atlas.preference.model');
        const model = mode === 'backend' ? configuration.current : preferredModel || configuration.current;
        set({ models: configuration.models, model, providerBaseUrl: configuration.gateway_base_url, apiKeyConfigured: configuration.api_key_configured, agentEngine: configuration.agent_engine ?? 'hermes', compressionModel: configuration.compression_model ?? '', configLoaded: true, conversations, ...flags(conversations), tools: toolList.tools, skills, capabilities, conversationsLoading: false });
        const first = conversations.find((item) => !item.archived);
        if (first) await get().openConversation(first);
        // Roles and recipes are extras; the app works without them if the backend predates them.
        const [profiles, recipes] = await Promise.all([backend.getProfiles().catch(() => []), backend.getRecipes().catch(() => [])]);
        set((state) => ({ profiles, recipes, profileId: profiles.some((profile) => profile.id === state.profileId) ? state.profileId : 'default' }));
      } catch (error) {
        fail(error, '无法读取后端数据');
        set({ conversationsLoading: false });
      }
    },

    openConversation: async (conversation) => {
      const run = [...get().runs].reverse().find((item) => item.conversationId === conversation.id);
      set((state) => ({ activeConversationId: conversation.id, activeRunId: run?.id ?? null, loadingMessagesConversationId: null, error: null, paused: run?.status === 'paused', unread: state.unread.filter((id) => id !== conversation.id) }));
      if (run && !terminal.has(run.status)) return;
      set({ loadingMessagesConversationId: conversation.id });
      try {
        await reloadMessages(conversation.id);
      } catch (error) {
        if (get().activeConversationId === conversation.id) fail(error, '无法读取对话历史');
      } finally {
        if (get().loadingMessagesConversationId === conversation.id) set({ loadingMessagesConversationId: null });
      }
    },

    createConversation: async (title = 'New conversation') => {
      if (get().creatingConversation) return;
      set({ creatingConversation: true });
      try {
        const conversation = await backend.createConversation(title);
        set((state) => ({
          conversations: [conversation, ...state.conversations.filter((item) => item.id !== conversation.id)],
          conversationMessages: { ...state.conversationMessages, [conversation.id]: [] },
          activeConversationId: conversation.id, activeRunId: null, paused: false, error: null,
        }));
      } catch (error) {
        fail(error, '无法创建新对话');
      } finally {
        set({ creatingConversation: false });
      }
    },

    selectModel: async (model) => {
      try { await backend.selectModel(model); storageSet('atlas.preference.model', model); set({ model }); }
      catch (error) { fail(error, '切换模型失败'); }
    },

    applySkill: (name) => set((state) => {
      const activeSkills = state.activeSkills.includes(name) ? state.activeSkills : [...state.activeSkills, name];
      storageSet(ACTIVE_SKILLS, JSON.stringify(activeSkills));
      return { activeSkills };
    }),
    removeSkill: (name) => set((state) => {
      const activeSkills = state.activeSkills.filter((item) => item !== name);
      storageSet(ACTIVE_SKILLS, JSON.stringify(activeSkills));
      return { activeSkills };
    }),

    saveProviderSettings: async (baseUrl, apiKey) => {
      set({ settingsBusy: true, connectionTest: null });
      try {
        const configuration: ConfigurationResponse = await backend.updateConfiguration(baseUrl, apiKey, undefined, get().compressionModel);
        set({ providerBaseUrl: configuration.gateway_base_url, apiKeyConfigured: configuration.api_key_configured, models: configuration.models, model: configuration.current, compressionModel: configuration.compression_model ?? '', error: null });
        return true;
      } catch (error) {
        set({ error: errorText(error, '保存 API 配置失败') });
        return false;
      } finally { set({ settingsBusy: false }); }
    },

    saveAgentEngine: async (engine) => {
      set({ settingsBusy: true, error: null });
      try {
        const configuration = await backend.updateConfiguration(get().providerBaseUrl, '', engine, get().compressionModel);
        set({ agentEngine: configuration.agent_engine, compressionModel: configuration.compression_model ?? '', error: null });
        return true;
      } catch (error) {
        set({ error: errorText(error, '无法切换 Agent 内核') });
        return false;
      } finally { set({ settingsBusy: false }); }
    },

    saveCompressionModel: async (compressionModel) => {
      set({ settingsBusy: true, error: null });
      try {
        const configuration = await backend.updateConfiguration(
          get().providerBaseUrl, '', get().agentEngine, compressionModel,
        );
        set({ compressionModel: configuration.compression_model ?? '', error: null });
        return true;
      } catch (error) {
        set({ error: errorText(error, '无法保存压缩模型') });
        return false;
      } finally { set({ settingsBusy: false }); }
    },

    addCustomModel: async (model) => {
      set({ settingsBusy: true, connectionTest: null });
      try {
        const configuration = await backend.addCustomModel(model);
        set({ models: configuration.models, providerBaseUrl: configuration.gateway_base_url, apiKeyConfigured: configuration.api_key_configured, model: configuration.current, error: null });
        return true;
      } catch (error) {
        set({ error: errorText(error, '保存模型配置失败') });
        return false;
      } finally { set({ settingsBusy: false }); }
    },

    testModelConnection: async (model) => {
      set({ settingsBusy: true, connectionTest: null });
      try {
        const result = await backend.testConnection(model);
        set({ connectionTest: { ok: result.ok, message: result.message }, error: null });
      } catch (error) {
        set({ connectionTest: { ok: false, message: errorText(error, '连接测试失败') } });
      } finally { set({ settingsBusy: false }); }
    },

    createRun: (conversationId, title) => {
      const timestamp = new Date().toISOString();
      const run: AgentRun = { id: crypto.randomUUID(), conversationId, title, status: 'planning', phase: 'planning', startedAt: timestamp, updatedAt: timestamp, lastEventSequence: 0, events: [] };
      // A queued message can start in a conversation the user is not looking at; don't pull the view over to it.
      set((state) => state.activeConversationId === conversationId
        ? { runs: [...state.runs, run], activeRunId: run.id, busy: true, paused: false, error: null }
        : { runs: [...state.runs, run], busy: true });
      return run;
    },

    appendEvent: (event) => {
      set((state) => {
        const current = state.runs.find((run) => run.id === event.runId);
        if (!current) return state;
        const updated = applyRuntimeEvent(current, event);
        if (updated === current) return state;
        let artifacts = state.artifacts;
        if (event.type === 'artifact.updated') {
          const data = event.data;
          const artifact: Artifact = {
            id: String(data.artifact_id ?? event.id), runId: event.runId,
            type: (['file', 'report', 'patch', 'image'].includes(String(data.artifact_type)) ? data.artifact_type : 'file') as Artifact['type'],
            name: String(data.name ?? data.path ?? 'Artifact'), path: typeof data.path === 'string' ? data.path : undefined,
            summary: String(data.summary ?? data.change ?? ''), createdAt: event.timestamp,
          };
          artifacts = [...state.artifacts.filter((item) => item.id !== artifact.id), artifact];
        }
        let pendingSteers = state.pendingSteers;
        if (event.type === 'run.steered') {
          pendingSteers = { ...pendingSteers, [event.runId]: (pendingSteers[event.runId] ?? []).filter((item) => item.id !== event.data.event_id) };
        }
        const runs = state.runs.map((run) => run.id === event.runId ? updated : run);
        const active = runs.find((run) => run.id === state.activeRunId);
        return { runs, artifacts, pendingSteers, busy: runs.some((run) => !terminal.has(run.status)), paused: active?.status === 'paused' };
      });
      const run = get().getRun(event.runId);
      if (!run) return;
      if (event.type === 'session.title' && event.data.accepted === true && typeof event.data.title === 'string') {
        patchConversation(run.conversationId, { title: event.data.title });
      }
      const title = get().conversations.find((item) => item.id === run.conversationId)?.title ?? run.title;
      if (event.type === 'approval.required' || event.type === 'input.required' || event.type === 'run.plan.proposed' || event.type === 'rules.trust_required') {
        const heading = event.type === 'input.required' ? 'Atlas 有个问题要问你' : event.type === 'run.plan.proposed' ? 'Atlas 的计划等你确认' : event.type === 'rules.trust_required' ? '要不要信任这个目录的规则文件？' : 'Atlas 需要你确认';
        notifyDesktop(heading, title, () => get().setActiveRun(run.id));
      }
      if (event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled') {
        const background = run.conversationId !== get().activeConversationId || (typeof document !== 'undefined' && !document.hasFocus());
        if (background) set((state) => ({ unread: state.unread.includes(run.conversationId) ? state.unread : [...state.unread, run.conversationId] }));
        notifyDesktop(`Atlas ${RUN_OUTCOME[event.type]}`, title, () => {
          const conversation = get().conversations.find((item) => item.id === run.conversationId);
          if (conversation) void get().openConversation(conversation);
        });
        // Steers the run never picked up are not lost: they run next, ahead of anything queued.
        const unconfirmed = get().pendingSteers[run.id] ?? [];
        if (unconfirmed.length) {
          set((state) => {
            const { [run.id]: _dropped, ...pendingSteers } = state.pendingSteers;
            return { pendingSteers, queue: { ...state.queue, [run.conversationId]: [...unconfirmed, ...(state.queue[run.conversationId] ?? [])] } };
          });
        }
        dispatchQueue(run.conversationId);
        void reloadMessages(run.conversationId).catch((error) => fail(error, '无法读取对话历史'));
        // The run may have created a worktree or remembered a directory for the conversation.
        void get().refreshConversations();
      }
    },

    getRun: (runId) => get().runs.find((run) => run.id === runId),
    setActiveRun: (runId) => {
      const run = get().runs.find((item) => item.id === runId);
      set({ activeRunId: runId, activeConversationId: run?.conversationId ?? get().activeConversationId, paused: run?.status === 'paused' });
    },
    removeRun: (runId) => set((state) => {
      const runs = state.runs.filter((run) => run.id !== runId);
      const activeRunId = state.activeRunId === runId ? null : state.activeRunId;
      const active = runs.find((run) => run.id === activeRunId);
      return { runs, artifacts: state.artifacts.filter((artifact) => artifact.runId !== runId), activeRunId, busy: runs.some((run) => !terminal.has(run.status)), paused: active?.status === 'paused' };
    }),

    sendMessage: async (content, attachments = [], files = [], refs, profileId) => {
      const message = content.trim() || (attachments.length || files.length ? '请查看附件。' : '');
      if (!message) return;
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission().catch(() => undefined);
      if (!get().activeConversationId) await get().createConversation(message.slice(0, 40) || 'New conversation');
      const conversationId = get().activeConversationId;
      if (!conversationId) return;
      const item: QueuedMessage = { id: crypto.randomUUID(), content: message, attachments, files, ...(refs && (refs.files.length || refs.conversations.length) ? { refs } : {}), ...(profileId ? { profileId } : {}) };
      const running = activeRunFor(conversationId);
      if (running) {
        // Attachments can't join a run in flight, so those always wait for the next run.
        if (get().followUpMode === 'steer' && !attachments.length && !files.length && !item.refs && !item.profileId && steer(running, item)) return;
        set((state) => ({ queue: { ...state.queue, [conversationId]: [...(state.queue[conversationId] ?? []), item] } }));
        return;
      }
      await startRun(conversationId, item);
    },

    approve: (eventId) => respondToApproval(eventId, 'allow'),
    reject: (eventId) => respondToApproval(eventId, 'deny'),
    answerInput: (runId, eventId, text) => {
      try {
        backend.respondToInput(runId, eventId, text);
        set((state) => ({ answers: { ...state.answers, [eventId]: text } }));
      } catch (error) { set({ error: errorText(error, '回答没有送达') }); }
    },
    trustRules: (runId, eventId, trust) => {
      try {
        backend.trustRules(runId, eventId, trust);
        set((state) => ({ answers: { ...state.answers, [eventId]: trust ? 'trusted' : 'declined' } }));
      } catch (error) { set({ error: errorText(error, '没能回复') }); }
    },
    setPermissionMode: (conversationId, mode) => get().setConversationSettings(conversationId, { permission_mode: mode }),
    setConversationSettings: (conversationId, patch) => {
      patchConversation(conversationId, patch);
      void backend.updateConversation(conversationId, patch).catch((error) => set({ error: errorText(error, '对话设置没能保存') }));
    },
    approvePlan: (runId, eventId, edits = '') => {
      try {
        backend.approvePlan(runId, eventId, edits.trim());
        set((state) => ({ answers: { ...state.answers, [eventId]: edits.trim() || 'approved' } }));
      } catch (error) { set({ error: errorText(error, '没能批准计划') }); }
    },

    togglePaused: () => {
      const runId = get().activeRunId;
      const run = runId ? get().getRun(runId) : undefined;
      if (!run || terminal.has(run.status)) return;
      try { backend.controlRun(run.id, run.status === 'paused' ? 'run.resume' : 'run.pause'); }
      catch (error) { set({ error: errorText(error, '运行控制请求失败') }); }
    },
    stopTask: () => { if (get().activeRunId) get().stopRun(get().activeRunId!); },
    stopRun: (runId) => {
      const run = get().getRun(runId);
      if (!run) return;
      if (get().queue[run.conversationId]?.length || get().pendingSteers[run.id]?.length) {
        set((state) => ({ queuePaused: { ...state.queuePaused, [run.conversationId]: true } }));
      }
      backend.cancelRun(run.id);
    },
    dismissError: () => set({ error: null }),
    setFollowUpMode: (followUpMode) => { storageSet(FOLLOW_UP, followUpMode); set({ followUpMode }); },
    setNextRunMode: (nextRunMode) => set({ nextRunMode }),

    removeQueued: (conversationId, id) => set((state) => {
      const rest = (state.queue[conversationId] ?? []).filter((item) => item.id !== id);
      return { queue: { ...state.queue, [conversationId]: rest }, queuePaused: rest.length ? state.queuePaused : { ...state.queuePaused, [conversationId]: false } };
    }),
    takeQueued: (conversationId, id) => {
      const item = get().queue[conversationId]?.find((entry) => entry.id === id);
      if (item) get().removeQueued(conversationId, id);
      return item;
    },
    sendQueuedNow: (conversationId, id) => {
      const items = get().queue[conversationId] ?? [];
      const item = items.find((entry) => entry.id === id);
      if (!item) return;
      set((state) => ({ queue: { ...state.queue, [conversationId]: [item, ...items.filter((entry) => entry.id !== id)] }, queuePaused: { ...state.queuePaused, [conversationId]: false } }));
      // Interrupt the current run; its terminal event dispatches the queue.
      const running = activeRunFor(conversationId);
      if (running) backend.cancelRun(running.id); else dispatchQueue(conversationId);
    },
    steerQueued: (conversationId, id) => {
      const running = activeRunFor(conversationId);
      const item = get().queue[conversationId]?.find((entry) => entry.id === id);
      if (!running || !item || item.attachments.length || item.files.length) return;
      get().removeQueued(conversationId, id);
      if (!steer(running, item)) set((state) => ({ queue: { ...state.queue, [conversationId]: [item, ...(state.queue[conversationId] ?? [])] } }));
    },
    resumeQueue: (conversationId) => {
      set((state) => ({ queuePaused: { ...state.queuePaused, [conversationId]: false } }));
      dispatchQueue(conversationId);
    },
    retryRun: (runId) => {
      const run = get().getRun(runId);
      const prompt = get().runPrompts[runId];
      if (!run || !prompt || !terminal.has(run.status)) return;
      void startRun(run.conversationId, { id: crypto.randomUUID(), ...prompt });
    },

    renameConversation: async (id, title) => {
      const next = title.trim();
      if (!next) return;
      try {
        await backend.renameConversation(id, next);
        patchConversation(id, { title: next });
      } catch (error) { set({ error: errorText(error, '改名失败') }); }
    },
    deleteConversation: async (id) => {
      const running = activeRunFor(id);
      if (running) backend.cancelRun(running.id);
      try {
        await backend.deleteConversation(id);
        set((state) => {
          const { [id]: _messages, ...conversationMessages } = state.conversationMessages;
          const { [id]: _queue, ...queue } = state.queue;
          const conversations = state.conversations.filter((item) => item.id !== id);
          const wasActive = state.activeConversationId === id;
          return {
            conversations, ...flags(conversations), conversationMessages, queue,
            unread: state.unread.filter((item) => item !== id),
            activeConversationId: wasActive ? '' : state.activeConversationId, activeRunId: wasActive ? null : state.activeRunId,
          };
        });
      } catch (error) { set({ error: errorText(error, '删除对话失败') }); }
    },
    togglePinned: (id) => {
      const pinned = !get().conversations.find((item) => item.id === id)?.pinned;
      patchConversation(id, { pinned });
      void backend.updateConversation(id, { pinned }).catch((error) => { patchConversation(id, { pinned: !pinned }); set({ error: errorText(error, '置顶没有保存') }); });
    },
    toggleArchived: (id) => {
      const current = get().conversations.find((item) => item.id === id);
      const patch = current?.archived ? { archived: false } : { archived: true, pinned: false };
      const undo = { archived: Boolean(current?.archived), pinned: Boolean(current?.pinned) };
      patchConversation(id, patch);
      void backend.updateConversation(id, patch).catch((error) => { patchConversation(id, undo); set({ error: errorText(error, '归档没有保存') }); });
    },
    exportConversation: async (id, format = 'json') => {
      const conversation = get().conversations.find((item) => item.id === id);
      try {
        const messages = await backend.getMessages(id);
        const safeTitle = (conversation?.title ?? id).replace(/[\\/:*?"<>|\s]+/g, '-').slice(0, 60);
        if (format === 'md') {
          const title = conversation?.title ?? '对话';
          const body = messages.filter((message) => message.role === 'user' || message.role === 'assistant')
            .map((message) => `## ${message.role === 'user' ? '我' : 'Atlas'}\n\n${message.content}`).join('\n\n');
          download(`atlas-${safeTitle}.md`, `# ${title}\n\n> 从 Atlas 导出于 ${new Date().toLocaleString()}\n\n${body}\n`, 'text/markdown');
          return;
        }
        downloadJson(`atlas-${safeTitle}.json`, { exported_at: new Date().toISOString(), conversation: conversation ?? { id }, messages });
      } catch (error) { set({ error: errorText(error, '导出失败') }); }
    },
    // The backend remembers the directory once a run uses it; until then it rides along with run.start.
    setWorkspace: (conversationId, workspace) => {
      if (workspace) get().setConversationSettings(conversationId, { workspace });
      else patchConversation(conversationId, { workspace });
    },

    editMessage: async (messageId, content) => {
      const conversationId = get().activeConversationId;
      if (!conversationId || activeRunFor(conversationId) || !content.trim()) return;
      try {
        await backend.truncateConversation(conversationId, messageId);
        set((state) => {
          const messages = state.conversationMessages[conversationId] ?? [];
          const cut = messages.findIndex((message) => message.id === messageId);
          return { conversationMessages: { ...state.conversationMessages, [conversationId]: cut >= 0 ? messages.slice(0, cut) : messages }, activeRunId: null };
        });
        await get().sendMessage(content);
      } catch (error) { set({ error: errorText(error, '没能修改这条消息') }); }
    },
    rewindTo: async (messageId, files) => {
      const conversationId = get().activeConversationId;
      if (!conversationId || activeRunFor(conversationId)) return null;
      try {
        const result = await backend.rewindConversation(conversationId, messageId, files);
        set({ activeRunId: null });
        await reloadMessages(conversationId);
        return result;
      } catch (error) { set({ error: errorText(error, '没能回退') }); return null; }
    },
    redoRewind: async (conversationId, rewindId) => {
      try {
        await backend.redoRewind(conversationId, rewindId);
        await reloadMessages(conversationId);
        return true;
      } catch (error) { set({ error: errorText(error, '没能重做') }); return false; }
    },
    forkFrom: async (messageId, summarize = false) => {
      const source = get().activeConversationId;
      if (!source) return;
      try {
        const fork = await backend.forkConversation(source, messageId, summarize);
        const workspace = get().conversations.find((item) => item.id === source)?.workspace;
        set((state) => ({ conversations: [{ ...fork, workspace: fork.workspace ?? workspace }, ...state.conversations] }));
        await get().openConversation(fork);
      } catch (error) { set({ error: errorText(error, '没能分叉') }); }
    },
    setProfile: (profileId) => { storageSet(PROFILE, profileId); set({ profileId }); },
    reloadProfiles: async () => {
      const profiles = await backend.getProfiles().catch(() => get().profiles);
      set((state) => ({ profiles, profileId: profiles.some((profile) => profile.id === state.profileId) ? state.profileId : 'default' }));
    },
    setReasoningEffort: (reasoningEffort) => { storageSet(REASONING, reasoningEffort || null); set({ reasoningEffort }); },
    requestWorktree: (conversationId, baseBranch) => set((state) => {
      const { [conversationId]: _previous, ...rest } = state.worktreeRequests;
      return { worktreeRequests: baseBranch === null ? rest : { ...rest, [conversationId]: baseBranch ? { base_branch: baseBranch } : {} } };
    }),
    refreshConversations: async () => {
      try {
        const loaded = await backend.getConversations();
        set((state) => {
          // Keep a directory chosen in the UI until the backend has remembered it from a run.
          const conversations = loaded.map((item) => {
            const local = state.conversations.find((entry) => entry.id === item.id);
            return !item.workspace && local?.workspace ? { ...item, workspace: local.workspace } : item;
          });
          return { conversations, ...flags(conversations) };
        });
      } catch { /* keep the current list */ }
    },
    duplicateConversation: async (id) => {
      try {
        const copy = await backend.duplicateConversation(id);
        const source = get().conversations.find((item) => item.id === id);
        set((state) => ({ conversations: [{ ...copy, workspace: copy.workspace ?? source?.workspace }, ...state.conversations] }));
        await get().openConversation(copy);
      } catch (error) { set({ error: errorText(error, '没能复制对话') }); }
    },
    messageSubtask: (runId, subtaskId, text) => backend.messageSubtask(runId, subtaskId, text),
    cancelSubtask: (runId, subtaskId) => { void backend.cancelSubtask(runId, subtaskId).catch((error) => set({ error: errorText(error, '没能停止子任务') })); },
    saveRecipe: async (runId, name) => {
      try {
        const recipe = await backend.recipeFromRun(runId, name.trim());
        set((state) => ({ recipes: [recipe, ...state.recipes.filter((item) => item.id !== recipe.id)] }));
        return true;
      } catch (error) { set({ error: errorText(error, '没能保存配方') }); return false; }
    },
    deleteRecipe: async (id) => {
      try { await backend.deleteRecipe(id); set((state) => ({ recipes: state.recipes.filter((item) => item.id !== id) })); }
      catch (error) { set({ error: errorText(error, '没能删除配方') }); }
    },
    runRecipe: async (id, params) => {
      try {
        const rendered = await backend.renderRecipe(id, params);
        if (rendered.mode === 'plan') set({ nextRunMode: 'plan' });
        if (rendered.profile_id) get().setProfile(rendered.profile_id);
        for (const skill of rendered.active_skills ?? []) get().applySkill(skill);
        const conversationId = get().activeConversationId;
        if (rendered.workspace && conversationId) get().setWorkspace(conversationId, rendered.workspace);
        await get().sendMessage(rendered.prompt);
      } catch (error) { set({ error: errorText(error, '配方没能运行') }); }
    },
    compactConversation: async (id, note = '') => {
      try {
        const result = await backend.compactConversation(id, note);
        return result.before_tokens && result.after_tokens ? `上下文从约 ${result.before_tokens} 压到 ${result.after_tokens} tokens` : '已压缩上下文';
      } catch (error) { set({ error: errorText(error, '压缩失败') }); return null; }
    },
  };
});

async function reloadMessages(conversationId: string) {
  const messages = await backend.getMessages(conversationId);
  useAtlasStore.setState((state) => ({ conversationMessages: { ...state.conversationMessages, [conversationId]: messages } }));
}

/** Push pins and archives saved by older builds to the backend, then forget the local copy. */
async function migrateLegacyFlags(conversations: ConversationSummary[]): Promise<ConversationSummary[]> {
  const pinned = new Set(readList(LEGACY_PINNED));
  const archived = new Set(readList(LEGACY_ARCHIVED));
  if (!pinned.size && !archived.size) return conversations;
  const updated = await Promise.all(conversations.map(async (item) => {
    const patch = { ...(pinned.has(item.id) && !item.pinned ? { pinned: true } : {}), ...(archived.has(item.id) && !item.archived ? { archived: true } : {}) };
    if (!Object.keys(patch).length) return item;
    try { await backend.updateConversation(item.id, patch); return { ...item, ...patch }; } catch { return item; }
  }));
  storageSet(LEGACY_PINNED, null);
  storageSet(LEGACY_ARCHIVED, null);
  return updated;
}

function respondToApproval(eventId: string, choice: 'allow' | 'deny') {
  const { getState: get, setState: set } = useAtlasStore;
  const run = get().runs.find((item) => item.events.some((event) => event.id === eventId && event.type === 'approval.required'));
  if (!run) return;
  try { backend.respondToApproval(run.id, { type: 'approval.response', event_id: eventId, choice }); }
  catch (error) { set({ error: errorText(error, choice === 'allow' ? '批准请求失败' : '拒绝请求失败') }); }
}

/** Fold a message into a running run. Returns false when it can't be delivered, so the caller can queue it. */
function steer(run: AgentRun, item: QueuedMessage): boolean {
  try { backend.steerRun(run.id, item.content, item.id); } catch { return false; }
  useAtlasStore.setState((state) => ({ pendingSteers: { ...state.pendingSteers, [run.id]: [...(state.pendingSteers[run.id] ?? []), item] } }));
  return true;
}

async function startRun(conversationId: string, item: QueuedMessage) {
  const { getState: get, setState: set } = useAtlasStore;
  const { content, attachments, files } = item;
  let conversation = get().conversations.find((entry) => entry.id === conversationId);
  if (conversation?.title === 'New conversation') {
    const title = content.slice(0, 40) || 'New conversation';
    try {
      await backend.renameConversation(conversation.id, title);
      set((state) => ({ conversations: state.conversations.map((entry) => entry.id === conversationId ? { ...entry, title } : entry) }));
      conversation = { ...conversation, title };
    } catch (error) {
      set({ error: errorText(error, '无法更新对话标题') });
    }
  }
  const mode = get().nextRunMode;
  const run = get().createRun(conversationId, conversation?.title ?? content.slice(0, 80));
  set((current) => ({ runPrompts: { ...current.runPrompts, [run.id]: { content, attachments, files, refs: item.refs } }, nextRunMode: 'act' }));
  const handleEvent = (envelope: RuntimeEventEnvelope) => {
    if (!isRuntimeEvent(envelope)) return;
    const event = normalizeRuntimeEvent(envelope);
    if (event) get().appendEvent(event);
  };
  const workspace = typeof conversation?.workspace === 'string' && conversation.workspace ? conversation.workspace : undefined;
  const state = get();
  const worktree = state.worktreeRequests[conversationId];
  const supportsEffort = Boolean(state.models.find((model) => model.id === state.model)?.supports_reasoning_effort);
  if (worktree) useAtlasStore.getState().requestWorktree(conversationId, null);
  void backend.startRun({
    type: 'run.start', run_id: run.id, content, conversation_id: run.conversationId, model: state.model, attachments, active_skills: state.activeSkills,
    ...(files.length ? { files } : {}), ...(mode === 'plan' ? { mode } : {}), ...(workspace ? { workspace } : {}),
    ...((item.profileId ?? state.profileId) !== 'default' ? { profile_id: item.profileId ?? state.profileId } : {}),
    ...(state.reasoningEffort && supportsEffort ? { reasoning_effort: state.reasoningEffort } : {}),
    ...(worktree && !conversation?.worktree_path ? { worktree } : {}),
    // Always explicit: the backend falls back to the conversation's saved settings when a field is missing.
    permission_mode: conversation?.permission_mode ?? 'full_access',
    executor: conversation?.executor || 'atlas',
    sandbox: conversation?.sandbox ?? null,
    allowed_paths: conversation?.allowed_paths ?? [],
    extra_roots: conversation?.extra_roots ?? [],
    ...(item.refs?.files.length ? { context_files: item.refs.files } : {}),
    ...(item.refs?.conversations.length ? { context_conversations: item.refs.conversations } : {}),
  }, handleEvent, () => get().getRun(run.id)?.status === 'paused')
    .catch((error) => {
      set({ mode: backend.mode, connected: backend.mode === 'backend', error: errorText(error, '运行启动失败') });
      const current = get().getRun(run.id);
      if (current && !terminal.has(current.status)) get().appendEvent({ id: `${run.id}:transport-failure`, runId: run.id, sequence: current.lastEventSequence + 1, type: 'run.failed', timestamp: new Date().toISOString(), data: { detail: errorText(error, '运行启动失败') } });
    });
}

function activeRunFor(conversationId: string): AgentRun | undefined {
  return useAtlasStore.getState().runs.find((run) => run.conversationId === conversationId && !terminal.has(run.status));
}

/** Start the next queued message once the conversation is idle, unless its queue was paused by Stop. */
function dispatchQueue(conversationId: string) {
  const { getState: get, setState: set } = useAtlasStore;
  const [next, ...rest] = get().queue[conversationId] ?? [];
  if (!next || get().queuePaused[conversationId] || activeRunFor(conversationId)) return;
  set((state) => ({ queue: { ...state.queue, [conversationId]: rest } }));
  void startRun(conversationId, next);
}

function downloadJson(filename: string, value: unknown) {
  download(filename, JSON.stringify(value, null, 2), 'application/json');
}

function download(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
