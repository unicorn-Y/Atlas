/** Persistent-Atlas store slice: agents / groups / channels / devices /
 * localModels / automations. Added in W9 without touching the semantics of the
 * existing conversation/run slices; mounted by spreading it into
 * `useAtlasStore` (see useAtlasStore.ts).
 *
 * All network calls go through `services/persistentApi.ts`, which mirrors the
 * Wave-1 REST routers. Failures surface as plain `*Error` strings — the slices
 * never throw into React.
 */
import type {
  ActivationReport, AgentHeartbeat, AgentStatus, AutomationRecord, AutomationRun,
  ChannelGatewayStatus, DeviceRecord, GroupRecord, GroupTimelineEntry,
  HandoffCard, LocalBackendRow, LocalCatalogRow, LocalHardware, LocalJob,
  LocalRuntimeStatus, MigrationReport, PersistentAgentRecord, TakeoverActivityEvent,
  TakeoverSnapshot,
} from '../services/persistentApi';
import {
  agentSkillsApi, agentsApi, automationsApi, channelsApi, devicesApi,
  groupsApi, localModelsApi,
} from '../services/persistentApi';

export interface AgentSkillRelationView { skill_name: string; enabled: boolean; relation: string; note?: string | null }

export interface PersistentState {
  agents: PersistentAgentRecord[];
  agentsLoading: boolean;
  agentsError: string | null;
  groups: GroupRecord[];
  /** null = never probed; false = backend answered 404 (W8 not mounted yet). */
  groupsAvailable: boolean | null;
  groupsLoading: boolean;
  groupsError: string | null;
  groupTimelines: Record<string, GroupTimelineEntry[]>;
  groupBusy: Record<string, boolean>;
  devices: DeviceRecord[];
  selfDeviceId: string;
  devicesLoading: boolean;
  devicesError: string | null;
  takeover: TakeoverSnapshot | null;
  deviceActivity: TakeoverActivityEvent[];
  handoffCards: HandoffCard[];
  channelStatus: ChannelGatewayStatus | null;
  channelStatusError: string | null;
  localStatus: LocalRuntimeStatus | null;
  localHardware: LocalHardware | null;
  localBackends: LocalBackendRow[];
  localCatalog: LocalCatalogRow[];
  localJobs: LocalJob[];
  localActivation: ActivationReport | null;
  localModelsError: string | null;
  localModelsBusy: boolean;
  automations: AutomationRecord[];
  automationsEngineStarted: boolean | null;
  automationsLoading: boolean;
  automationsError: string | null;
  automationRuns: Record<string, AutomationRun[]>;
  migrationReport: MigrationReport | null;
}

export interface PersistentActions {
  loadAgents: () => Promise<void>;
  createAgent: (payload: Record<string, unknown>) => Promise<PersistentAgentRecord | null>;
  updateAgent: (id: string, patch: Record<string, unknown>) => Promise<PersistentAgentRecord | null>;
  deleteAgent: (id: string) => Promise<boolean>;
  setAgentEnabled: (id: string, enabled: boolean) => Promise<void>;
  setAgentHeartbeat: (id: string, config: Partial<AgentHeartbeat>) => Promise<boolean>;
  setAgentSkills: (id: string, skills: Array<{ skill_name: string; enabled: boolean; relation?: string; note?: string }>) => Promise<boolean>;
  loadGroups: () => Promise<void>;
  createGroup: (name: string, memberIds: string[]) => Promise<boolean>;
  updateGroup: (id: string, patch: Partial<GroupRecord>) => Promise<boolean>;
  deleteGroup: (id: string) => Promise<void>;
  sendGroupTurn: (id: string, text: string) => Promise<boolean>;
  loadGroupTimeline: (id: string) => Promise<void>;
  stopGroup: (id: string) => Promise<void>;
  loadDevices: () => Promise<void>;
  patchDevice: (id: string, patch: Record<string, unknown>) => Promise<void>;
  removeDevice: (id: string) => Promise<void>;
  registerDevice: (payload: { device_id: string; display_name: string; kind?: string; os?: string; notes?: string }) => Promise<boolean>;
  takeoverAction: (action: 'human_take' | 'agent_take' | 'release', options?: { agentId?: string; note?: string }) => Promise<boolean>;
  loadTakeoverContext: () => Promise<void>;
  handoffAction: (action: 'open' | 'done' | 'give_up', options?: { cardId?: string; note?: string }) => Promise<boolean>;
  loadChannelStatus: () => Promise<void>;
  loadLocalModels: () => Promise<void>;
  refreshLocalJobs: () => Promise<void>;
  installLocalRuntime: (backend?: string | null) => Promise<boolean>;
  startModelDownload: (modelId: string) => Promise<boolean>;
  sideloadLocalModel: (path: string) => Promise<boolean>;
  activateLocalModel: (modelId: string) => Promise<boolean>;
  ejectLocalModel: (modelId: string) => Promise<void>;
  localModelServerAction: (action: 'start' | 'stop') => Promise<boolean>;
  pauseOrResumeDownload: (jobId: string, action: 'pause' | 'resume') => Promise<void>;
  loadAutomations: () => Promise<void>;
  createAutomation: (payload: Record<string, unknown>) => Promise<AutomationRecord | null>;
  patchAutomation: (id: string, patch: Record<string, unknown>) => Promise<boolean>;
  deleteAutomation: (id: string) => Promise<void>;
  runAutomationNow: (id: string) => Promise<boolean>;
  pauseAutomation: (id: string) => Promise<void>;
  resumeAutomation: (id: string) => Promise<void>;
  loadAutomationRuns: (id: string) => Promise<void>;
  importLegacyAutomations: () => Promise<MigrationReport | null>;
}

export type PersistentSlice = PersistentState & PersistentActions;

const errorText = (error: unknown): string => (error instanceof Error ? error.message : String(error));
/** The api() helper renders status codes as `HTTP 404：…`; groups rely on that. */
const isNotFound = (error: unknown): boolean => /\bHTTP 404\b/.test(errorText(error));

export function createPersistentSlice(
  set: (partial: Partial<PersistentSlice> | ((state: PersistentSlice) => Partial<PersistentSlice>)) => void,
  get: () => PersistentSlice & { apiBaseUrl: string },
): PersistentSlice {
  const base = () => get().apiBaseUrl;
  return {
    agents: [], agentsLoading: false, agentsError: null,
    groups: [], groupsAvailable: null, groupsLoading: false, groupsError: null, groupTimelines: {}, groupBusy: {},
    devices: [], selfDeviceId: '', devicesLoading: false, devicesError: null,
    takeover: null, deviceActivity: [], handoffCards: [],
    channelStatus: null, channelStatusError: null,
    localStatus: null, localHardware: null, localBackends: [], localCatalog: [], localJobs: [], localActivation: null,
    localModelsError: null, localModelsBusy: false,
    automations: [], automationsEngineStarted: null, automationsLoading: false, automationsError: null,
    automationRuns: {}, migrationReport: null,

    // -- agents ---------------------------------------------------------
    loadAgents: async () => {
      set({ agentsLoading: true, agentsError: null });
      try { set({ agents: await agentsApi.list(base()), agentsLoading: false }); }
      catch (error) { set({ agentsLoading: false, agentsError: errorText(error) }); }
    },
    createAgent: async (payload) => {
      try {
        const agent = await agentsApi.create(base(), payload);
        set((state) => ({ agents: [...state.agents.filter((item) => item.id !== agent.id), agent] }));
        return agent;
      } catch (error) { set({ agentsError: errorText(error) }); return null; }
    },
    updateAgent: async (id, patch) => {
      try {
        const agent = await agentsApi.patch(base(), id, patch);
        set((state) => ({ agents: state.agents.map((item) => item.id === id ? agent : item) }));
        return agent;
      } catch (error) { set({ agentsError: errorText(error) }); return null; }
    },
    deleteAgent: async (id) => {
      try {
        await agentsApi.remove(base(), id);
        set((state) => ({ agents: state.agents.filter((item) => item.id !== id) }));
        return true;
      } catch (error) { set({ agentsError: errorText(error) }); return false; }
    },
    setAgentEnabled: async (id, enabled) => {
      await get().updateAgent(id, { agent: { enabled } });
    },
    setAgentHeartbeat: async (id, config) => {
      try {
        const result = await agentsApi.putHeartbeat(base(), id, config);
        set((state) => ({
          agents: state.agents.map((item) => item.id === id
            ? { ...item, agent: { ...item.agent, heartbeat: result.heartbeat } } : item),
        }));
        return true;
      } catch (error) { set({ agentsError: errorText(error) }); return false; }
    },
    setAgentSkills: async (id, skills) => {
      try { await agentSkillsApi.set(base(), id, skills); return true; }
      catch (error) { set({ agentsError: errorText(error) }); return false; }
    },

    // -- groups ---------------------------------------------------------
    loadGroups: async () => {
      set({ groupsLoading: true, groupsError: null });
      try {
        const groups = await groupsApi.list(base());
        set({ groups, groupsAvailable: true, groupsLoading: false });
      } catch (error) {
        set({ groupsLoading: false, groupsAvailable: isNotFound(error) ? false : true, groupsError: isNotFound(error) ? null : errorText(error) });
      }
    },
    createGroup: async (name, memberIds) => {
      set({ groupsError: null });
      try {
        const group = await groupsApi.create(base(), name, memberIds);
        set((state) => ({ groups: [...state.groups.filter((item) => item.id !== group.id), group], groupsAvailable: true }));
        return true;
      } catch (error) {
        set({ groupsAvailable: isNotFound(error) ? false : get().groupsAvailable, groupsError: isNotFound(error) ? null : errorText(error) });
        return false;
      }
    },
    updateGroup: async (id, patch) => {
      try {
        const group = await groupsApi.update(base(), id, patch);
        set((state) => ({ groups: state.groups.map((item) => item.id === id ? group : item), groupsError: null }));
        return true;
      } catch (error) {
        set({ groupsError: errorText(error) });
        return false;
      }
    },
    deleteGroup: async (id) => {
      try { await groupsApi.remove(base(), id); } catch { /* remove locally even if the backend lost it first */ }
      set((state) => {
        const { [id]: _timeline, ...groupTimelines } = state.groupTimelines;
        return { groups: state.groups.filter((item) => item.id !== id), groupTimelines };
      });
    },
    sendGroupTurn: async (id, text) => {
      set((state) => ({ groupBusy: { ...state.groupBusy, [id]: true }, groupsError: null }));
      try {
        await groupsApi.turn(base(), id, text);
        await get().loadGroupTimeline(id);
        return true;
      } catch (error) {
        set({ groupsError: isNotFound(error) ? '群聊服务未就绪' : errorText(error), groupsAvailable: isNotFound(error) ? false : get().groupsAvailable });
        return false;
      } finally {
        set((state) => {
          const { [id]: _busy, ...groupBusy } = state.groupBusy;
          return { groupBusy };
        });
      }
    },
    loadGroupTimeline: async (id) => {
      try {
        const body = await groupsApi.timeline(base(), id);
        const entries = body.entries ?? body.timeline ?? body.log ?? [];
        set((state) => ({ groupTimelines: { ...state.groupTimelines, [id]: entries } }));
      } catch (error) {
        if (isNotFound(error)) set({ groupsAvailable: false });
      }
    },
    stopGroup: async (id) => {
      try { await groupsApi.stop(base(), id); await get().loadGroupTimeline(id); }
      catch (error) { set({ groupsError: errorText(error) }); }
    },

    // -- devices + takeover ----------------------------------------------
    loadDevices: async () => {
      set({ devicesLoading: true, devicesError: null });
      try {
        const body = await devicesApi.list(base());
        set({ devices: body.devices, selfDeviceId: body.self, devicesLoading: false });
      } catch (error) { set({ devicesLoading: false, devicesError: errorText(error) }); }
    },
    patchDevice: async (id, patch) => {
      try {
        const device = await devicesApi.patch(base(), id, patch);
        set((state) => ({ devices: state.devices.map((item) => item.id === id ? device : item) }));
      } catch (error) { set({ devicesError: errorText(error) }); }
    },
    removeDevice: async (id) => {
      try {
        await devicesApi.remove(base(), id);
        set((state) => ({ devices: state.devices.filter((item) => item.id !== id) }));
      } catch (error) { set({ devicesError: errorText(error) }); }
    },
    registerDevice: async (payload) => {
      try {
        const device = await devicesApi.register(base(), payload);
        set((state) => ({ devices: [...state.devices.filter((item) => item.id !== device.id), device] }));
        return true;
      } catch (error) { set({ devicesError: errorText(error) }); return false; }
    },
    takeoverAction: async (action, options = {}) => {
      try {
        const snapshot = await devicesApi.takeoverAction(base(), action, options);
        set({ takeover: {
          device_id: String(snapshot.device_id ?? ''),
          state: snapshot.state as TakeoverSnapshot['state'],
          holder: String(snapshot.holder ?? ''),
          needs_observation: Boolean(snapshot.needs_observation),
          since_ts: typeof snapshot.since_ts === 'number' ? snapshot.since_ts : undefined,
          pending_handoff: typeof snapshot.pending_handoff === 'number' ? snapshot.pending_handoff : undefined,
        } });
        await get().loadTakeoverContext();
        return true;
      } catch (error) { set({ devicesError: errorText(error) }); return false; }
    },
    loadTakeoverContext: async () => {
      try {
        const [takeover, activity, handoff] = await Promise.all([
          devicesApi.takeover(base()),
          devicesApi.activity(base(), 40).catch(() => ({ activity: [] as TakeoverActivityEvent[] })),
          devicesApi.handoff(base()).catch(() => ({ cards: [] as HandoffCard[] })),
        ]);
        set({ takeover, deviceActivity: activity.activity, handoffCards: handoff.cards });
      } catch (error) { set({ devicesError: errorText(error) }); }
    },
    handoffAction: async (action, options = {}) => {
      try {
        await devicesApi.handoffAction(base(), action, options);
        await get().loadTakeoverContext();
        return true;
      } catch (error) { set({ devicesError: errorText(error) }); return false; }
    },

    // -- channel gateway ---------------------------------------------------
    loadChannelStatus: async () => {
      set({ channelStatusError: null });
      try { set({ channelStatus: await channelsApi.status(base()) }); }
      catch (error) { set({ channelStatusError: errorText(error) }); }
    },

    // -- managed local models ----------------------------------------------
    loadLocalModels: async () => {
      set({ localModelsBusy: true, localModelsError: null });
      const b = base();
      const soft = <T,>(promise: Promise<T>, fallback: T): Promise<T> => promise.catch(() => fallback);
      try {
        const [status, hardware, backends, catalog, jobs] = await Promise.all([
          localModelsApi.status(b),
          soft(localModelsApi.hardware(b), {} as LocalHardware),
          soft(localModelsApi.backends(b), { backends: [] as LocalBackendRow[] }),
          soft(localModelsApi.catalog(b), { models: [] as LocalCatalogRow[] }),
          soft(localModelsApi.jobs(b), { jobs: [] as LocalJob[] }),
        ]);
        set({
          localStatus: status, localHardware: hardware, localBackends: backends.backends,
          localCatalog: catalog.models, localJobs: jobs.jobs, localModelsBusy: false,
        });
      } catch (error) { set({ localModelsBusy: false, localModelsError: errorText(error) }); }
    },
    refreshLocalJobs: async () => {
      try { set({ localJobs: (await localModelsApi.jobs(base())).jobs }); } catch { /* transient poll failure */ }
    },
    installLocalRuntime: async (backend = null) => {
      set({ localModelsError: null });
      try { await localModelsApi.installRuntime(base(), backend); await get().refreshLocalJobs(); return true; }
      catch (error) { set({ localModelsError: errorText(error) }); return false; }
    },
    startModelDownload: async (modelId) => {
      set({ localModelsError: null });
      try { await localModelsApi.download(base(), modelId); await get().refreshLocalJobs(); return true; }
      catch (error) { set({ localModelsError: errorText(error) }); return false; }
    },
    sideloadLocalModel: async (path) => {
      set({ localModelsError: null });
      try { await localModelsApi.sideload(base(), path); await get().loadLocalModels(); return true; }
      catch (error) { set({ localModelsError: errorText(error) }); return false; }
    },
    activateLocalModel: async (modelId) => {
      set({ localModelsBusy: true, localModelsError: null, localActivation: null });
      try {
        const report = await localModelsApi.activate(base(), modelId);
        set({ localActivation: report, localModelsBusy: false });
        const status = await localModelsApi.status(base()).catch(() => null);
        if (status) set({ localStatus: status });
        return report.ok;
      } catch (error) { set({ localModelsBusy: false, localModelsError: errorText(error) }); return false; }
    },
    ejectLocalModel: async (modelId) => {
      try { await localModelsApi.eject(base(), modelId); await get().loadLocalModels(); }
      catch (error) { set({ localModelsError: errorText(error) }); }
    },
    localModelServerAction: async (action) => {
      set({ localModelsError: null });
      try {
        await localModelsApi.server(base(), action);
        const status = await localModelsApi.status(base()).catch(() => null);
        if (status) set({ localStatus: status });
        return true;
      } catch (error) { set({ localModelsError: errorText(error) }); return false; }
    },
    pauseOrResumeDownload: async (jobId, action) => {
      try {
        if (action === 'pause') await localModelsApi.pauseDownload(base(), jobId);
        else await localModelsApi.resumeDownload(base(), jobId);
        await get().refreshLocalJobs();
      } catch (error) { set({ localModelsError: errorText(error) }); }
    },

    // -- automations ---------------------------------------------------------
    loadAutomations: async () => {
      set({ automationsLoading: true, automationsError: null });
      try {
        const body = await automationsApi.list(base());
        set({ automations: body.automations, automationsEngineStarted: body.engine_started, automationsLoading: false });
      } catch (error) { set({ automationsLoading: false, automationsError: errorText(error) }); }
    },
    createAutomation: async (payload) => {
      set({ automationsError: null });
      try {
        const body = await automationsApi.create(base(), payload);
        set((state) => ({ automations: [...state.automations.filter((item) => item.id !== body.automation.id), body.automation] }));
        return body.automation;
      } catch (error) { set({ automationsError: errorText(error) }); return null; }
    },
    patchAutomation: async (id, patch) => {
      set({ automationsError: null });
      try {
        const body = await automationsApi.patch(base(), id, patch);
        set((state) => ({ automations: state.automations.map((item) => item.id === id ? body.automation : item) }));
        return true;
      } catch (error) { set({ automationsError: errorText(error) }); return false; }
    },
    deleteAutomation: async (id) => {
      try {
        await automationsApi.remove(base(), id);
        set((state) => {
          const { [id]: _runs, ...automationRuns } = state.automationRuns;
          return { automations: state.automations.filter((item) => item.id !== id), automationRuns };
        });
      } catch (error) { set({ automationsError: errorText(error) }); }
    },
    runAutomationNow: async (id) => {
      set({ automationsError: null });
      try { await automationsApi.runNow(base(), id); await get().loadAutomations(); return true; }
      catch (error) { set({ automationsError: errorText(error) }); return false; }
    },
    pauseAutomation: async (id) => {
      try { await automationsApi.pause(base(), id); await get().loadAutomations(); }
      catch (error) { set({ automationsError: errorText(error) }); }
    },
    resumeAutomation: async (id) => {
      try { await automationsApi.resume(base(), id); await get().loadAutomations(); }
      catch (error) { set({ automationsError: errorText(error) }); }
    },
    loadAutomationRuns: async (id) => {
      try {
        const runs = (await automationsApi.runs(base(), id)).runs;
        set((state) => ({ automationRuns: { ...state.automationRuns, [id]: runs } }));
      } catch (error) { set({ automationsError: errorText(error) }); }
    },
    importLegacyAutomations: async () => {
      set({ automationsError: null });
      try {
        const report = await automationsApi.importLegacy(base());
        set({ migrationReport: report });
        await get().loadAutomations();
        return report;
      } catch (error) { set({ automationsError: errorText(error) }); return null; }
    },
  };
}

/** Status badge metadata shared by the agents list and the activity tab. */
export const AGENT_STATUS_META: Record<AgentStatus, { label: string; className: string }> = {
  idle: { label: '空闲', className: 'text-fg-3' },
  working: { label: '工作中', className: 'text-brand' },
  waiting_user: { label: '等你确认', className: 'text-danger' },
  offline: { label: '离线', className: 'text-fg-3' },
};
