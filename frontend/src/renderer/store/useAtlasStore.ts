import { create } from 'zustand';
import { BackendAdapter } from '@atlas/backend-adapter';
import type { ConversationMessage, ConversationSummary, ModelListResponse, RuntimeEventEnvelope, ToolListResponse } from '@atlas/backend-adapter';
import type { AgentEvent, AgentRun, AgentRunStatus } from '../../types/runtime';
import type { Artifact } from '../../types/artifact';
import { applyRuntimeEvent, isRuntimeEvent, normalizeRuntimeEvent } from '../services/runtimeEvents';

const backend = new BackendAdapter({ baseUrl: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8765' });

interface AtlasState {
  apiBaseUrl: string;
  mode: 'mock' | 'backend';
  connected: boolean;
  busy: boolean;
  paused: boolean;
  error: string | null;
  model: string;
  models: ModelListResponse['models'];
  tools: ToolListResponse['tools'];
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  loadingMessagesConversationId: string | null;
  creatingConversation: boolean;
  conversationMessages: Record<string, ConversationMessage[]>;
  activeConversationId: string;
  runs: AgentRun[];
  activeRunId: string | null;
  artifacts: Artifact[];
  initialize: () => Promise<void>;
  openConversation: (conversation: ConversationSummary) => Promise<void>;
  createConversation: (title?: string) => Promise<void>;
  selectModel: (model: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  createRun: (conversationId: string, title: string) => AgentRun;
  appendEvent: (event: AgentEvent) => void;
  getRun: (runId: string) => AgentRun | undefined;
  setActiveRun: (runId: string | null) => void;
  removeRun: (runId: string) => void;
  approve: (eventId: string) => void;
  reject: (eventId: string) => void;
  togglePaused: () => void;
  stopTask: () => void;
  dismissError: () => void;
}

const terminal = new Set<AgentRunStatus>(['completed', 'failed', 'cancelled']);

export const useAtlasStore = create<AtlasState>((set, get) => ({
  apiBaseUrl: backend.apiBaseUrl, mode: 'mock', connected: false, busy: false, paused: false, error: null,
  model: '', models: [], tools: [], conversations: [], conversationsLoading: false, loadingMessagesConversationId: null, creatingConversation: false, conversationMessages: {}, activeConversationId: '',
  runs: [], activeRunId: null, artifacts: [],

  initialize: async () => {
    set({ conversationsLoading: true });
    const mode = await backend.initialize();
    set({ mode, connected: mode === 'backend', error: mode === 'mock' ? backend.availabilityError : null });
    try {
      const [models, conversations, toolList] = await Promise.all([backend.getModels(), backend.getConversations(), backend.getTools()]);
      set({ models: models.models, model: models.current, conversations, tools: toolList.tools, conversationsLoading: false });
      if (conversations.length) await get().openConversation(conversations[0]);
    } catch (error) {
      set({ mode: backend.mode, connected: backend.mode === 'backend', error: error instanceof Error ? error.message : '无法读取后端数据', conversationsLoading: false });
    }
  },

  openConversation: async (conversation) => {
    const run = [...get().runs].reverse().find((item) => item.conversationId === conversation.id);
    set({ activeConversationId: conversation.id, activeRunId: run?.id ?? null, loadingMessagesConversationId: null, error: null, paused: run?.status === 'paused' });
    if (run && !terminal.has(run.status)) return;

    set({ loadingMessagesConversationId: conversation.id });
    try {
      const messages = await backend.getMessages(conversation.id);
      set((state) => ({ conversationMessages: { ...state.conversationMessages, [conversation.id]: messages } }));
    } catch (error) {
      if (get().activeConversationId === conversation.id) {
        set({ mode: backend.mode, connected: backend.mode === 'backend', error: error instanceof Error ? error.message : '无法读取对话历史' });
      }
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
        activeConversationId: conversation.id,
        activeRunId: null,
        paused: false,
        error: null,
      }));
    } catch (error) {
      set({ mode: backend.mode, connected: backend.mode === 'backend', error: error instanceof Error ? error.message : '无法创建新对话' });
    } finally {
      set({ creatingConversation: false });
    }
  },

  selectModel: async (model) => {
    try { await backend.selectModel(model); set({ model }); }
    catch (error) { set({ mode: backend.mode, connected: backend.mode === 'backend', error: error instanceof Error ? error.message : '切换模型失败' }); }
  },

  createRun: (conversationId, title) => {
    const timestamp = new Date().toISOString();
    const run: AgentRun = { id: crypto.randomUUID(), conversationId, title, status: 'planning', phase: 'planning', startedAt: timestamp, updatedAt: timestamp, lastEventSequence: 0, events: [] };
    set((state) => ({ runs: [...state.runs, run], activeRunId: run.id, busy: true, paused: false, error: null }));
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
      const runs = state.runs.map((run) => run.id === event.runId ? updated : run);
      const active = runs.find((run) => run.id === state.activeRunId);
      return { runs, artifacts, busy: runs.some((run) => !terminal.has(run.status)), paused: active?.status === 'paused' };
    });
    if (event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled') {
      const run = get().runs.find((item) => item.id === event.runId);
      if (run) {
        void backend.getMessages(run.conversationId).then((messages) => {
          set((state) => ({ conversationMessages: { ...state.conversationMessages, [run.conversationId]: messages } }));
        }).catch((error) => {
          set({ mode: backend.mode, connected: backend.mode === 'backend', error: error instanceof Error ? error.message : '无法读取对话历史' });
        });
      }
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

  sendMessage: async (content) => {
    const message = content.trim();
    if (!message) return;
    if (!get().activeConversationId) await get().createConversation(message.slice(0, 40) || 'New conversation');
    let conversationId = get().activeConversationId;
    if (!conversationId) return;
    let conversation = get().conversations.find((item) => item.id === conversationId);
    if (conversation?.title === 'New conversation') {
      const title = message.slice(0, 40) || 'New conversation';
      try {
        await backend.renameConversation(conversation.id, title);
        set((state) => ({ conversations: state.conversations.map((item) => item.id === conversationId ? { ...item, title } : item) }));
        conversation = { ...conversation, title };
      } catch (error) {
        set({ error: error instanceof Error ? error.message : '无法更新对话标题' });
      }
    }
    const run = get().createRun(conversationId, conversation?.title ?? message.slice(0, 80));
    const handleEvent = (envelope: RuntimeEventEnvelope) => {
      if (!isRuntimeEvent(envelope)) return;
      const event = normalizeRuntimeEvent(envelope);
      if (event) get().appendEvent(event);
    };
    void backend.startRun({ type: 'run.start', run_id: run.id, content: message, conversation_id: run.conversationId, model: get().model }, handleEvent, () => get().getRun(run.id)?.status === 'paused')
      .catch((error) => {
        set({ mode: backend.mode, connected: backend.mode === 'backend', error: error instanceof Error ? error.message : '运行启动失败' });
        const current = get().getRun(run.id);
        if (current && !terminal.has(current.status)) get().appendEvent({ id: `${run.id}:transport-failure`, runId: run.id, sequence: current.lastEventSequence + 1, type: 'run.failed', timestamp: new Date().toISOString(), data: { detail: error instanceof Error ? error.message : '运行启动失败' } });
      });
  },

  approve: (eventId) => {
    const run = get().runs.find((item) => item.events.some((event) => event.id === eventId && event.type === 'approval.required'));
    if (!run) return;
    try { backend.respondToApproval(run.id, { type: 'approval.response', event_id: eventId, choice: 'allow' }); }
    catch (error) { set({ error: error instanceof Error ? error.message : '批准请求失败' }); }
  },
  reject: (eventId) => {
    const run = get().runs.find((item) => item.events.some((event) => event.id === eventId && event.type === 'approval.required'));
    if (!run) return;
    try { backend.respondToApproval(run.id, { type: 'approval.response', event_id: eventId, choice: 'deny' }); }
    catch (error) { set({ error: error instanceof Error ? error.message : '拒绝请求失败' }); }
  },

  togglePaused: () => {
    const runId = get().activeRunId;
    const run = runId ? get().getRun(runId) : undefined;
    if (!run || terminal.has(run.status)) return;
    try { backend.controlRun(run.id, run.status === 'paused' ? 'run.resume' : 'run.pause'); }
    catch (error) { set({ error: error instanceof Error ? error.message : '运行控制请求失败' }); }
  },
  stopTask: () => { if (get().activeRunId) backend.cancelRun(get().activeRunId!); },
  dismissError: () => set({ error: null }),
}));
