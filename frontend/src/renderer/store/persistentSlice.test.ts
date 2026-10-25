import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/persistentApi', () => ({
  agentsApi: {
    list: vi.fn(), create: vi.fn(), get: vi.fn(), patch: vi.fn(), remove: vi.fn(),
    status: vi.fn(), putHeartbeat: vi.fn(), listChannels: vi.fn(), addChannel: vi.fn(), removeChannel: vi.fn(),
  },
  agentSkillsApi: { list: vi.fn(), set: vi.fn(), proposals: vi.fn(), approve: vi.fn(), reject: vi.fn(), rollback: vi.fn() },
  groupsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), turn: vi.fn(), timeline: vi.fn(), stop: vi.fn() },
  automationsApi: { list: vi.fn(), create: vi.fn(), patch: vi.fn(), remove: vi.fn(), runNow: vi.fn(), cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(), runs: vi.fn(), importLegacy: vi.fn() },
  devicesApi: { list: vi.fn(), register: vi.fn(), patch: vi.fn(), remove: vi.fn(), takeover: vi.fn(), takeoverAction: vi.fn(), activity: vi.fn(), handoff: vi.fn(), handoffAction: vi.fn() },
  channelsApi: { status: vi.fn(), putAccounts: vi.fn(), setCredential: vi.fn(), sendTest: vi.fn() },
  localModelsApi: {
    status: vi.fn(), hardware: vi.fn(), backends: vi.fn(), catalog: vi.fn(), search: vi.fn(), installRuntime: vi.fn(),
    download: vi.fn(), pauseDownload: vi.fn(), resumeDownload: vi.fn(), jobs: vi.fn(), deleteModel: vi.fn(),
    sideload: vi.fn(), server: vi.fn(), activate: vi.fn(), eject: vi.fn(), diagnostics: vi.fn(),
  },
}));

import { agentsApi, groupsApi } from '../services/persistentApi';
import { AGENT_STATUS_META, createPersistentSlice, type PersistentSlice } from './persistentSlice';

type Slice = PersistentSlice & { apiBaseUrl: string };

function makeStore() {
  const state: Record<string, unknown> = { apiBaseUrl: 'http://test' };
  const asSlice = () => state as unknown as Slice;
  const set = (partial: Partial<Slice> | ((current: Slice) => Partial<Slice>)) => {
    Object.assign(state, typeof partial === 'function' ? partial(asSlice()) : partial);
  };
  const get = () => asSlice();
  const slice = createPersistentSlice(set, get);
  // 真实 store 会把 slice 摊开进全局状态，动作之间靠 get() 互调；这里保持一致。
  Object.assign(state, slice);
  return { state: state as unknown as Slice, slice };
}

beforeEach(() => vi.clearAllMocks());

describe('persistent slice', () => {
  it('loadAgents stores the list and surfaces failures as a string', async () => {
    const { state, slice } = makeStore();
    vi.mocked(agentsApi.list).mockResolvedValue([{ id: 'a1', name: 'rabbit', kind: 'persistent', status: 'idle' }]);
    await slice.loadAgents();
    expect(state.agents).toHaveLength(1);
    expect(state.agentsError).toBeNull();

    vi.mocked(agentsApi.list).mockRejectedValue(new Error('boom'));
    await slice.loadAgents();
    expect(state.agentsError).toBe('boom');
  });

  it('marks the group service unavailable on HTTP 404 (W8 not mounted) without an error banner', async () => {
    const { state, slice } = makeStore();
    vi.mocked(groupsApi.list).mockRejectedValue(new Error('HTTP 404：Not Found'));
    await slice.loadGroups();
    expect(state.groupsAvailable).toBe(false);
    expect(state.groupsError).toBeNull();

    vi.mocked(groupsApi.list).mockRejectedValue(new Error('HTTP 500：boom'));
    await slice.loadGroups();
    expect(state.groupsAvailable).toBe(true); // 只有 404 视为“未挂载”；其余错误照常报错、列表仍显示
    expect(state.groupsError).toBe('HTTP 500：boom');
  });

  it('sendGroupTurn reloads the timeline and degrades to the placeholder copy on 404', async () => {
    const { state, slice } = makeStore();
    vi.mocked(groupsApi.turn).mockRejectedValue(new Error('HTTP 404：group router missing'));
    vi.mocked(groupsApi.timeline).mockResolvedValue({ entries: [{ actor_kind: 'user', text: 'hi' }] });
    expect(await slice.sendGroupTurn('g1', 'hello')).toBe(false);
    expect(state.groupsError).toBe('群聊服务未就绪');

    vi.mocked(groupsApi.turn).mockResolvedValue({});
    vi.mocked(groupsApi.timeline).mockClear();
    expect(await slice.sendGroupTurn('g1', 'hello')).toBe(true);
    expect(groupsApi.timeline).toHaveBeenCalledWith('http://test', 'g1');
  });

  it('persists group topic routes and replaces the current group record', async () => {
    const { state, slice } = makeStore();
    state.groups = [{ id: 'g1', name: 'Review', member_agent_ids: ['ops'] }];
    const updated = { id: 'g1', name: 'Review', topic_routes: [{ id: 'deploy', keywords: ['deploy'], agent_ids: ['ops'], priority: 2, enabled: true }] };
    vi.mocked(groupsApi.update).mockResolvedValue(updated);
    expect(await slice.updateGroup('g1', { topic_routes: updated.topic_routes })).toBe(true);
    expect(groupsApi.update).toHaveBeenCalledWith('http://test', 'g1', { topic_routes: updated.topic_routes });
    expect(state.groups[0].topic_routes).toEqual(updated.topic_routes);
  });

  it('status meta covers the four projected states', () => {
    expect(Object.keys(AGENT_STATUS_META).sort()).toEqual(['idle', 'offline', 'waiting_user', 'working']);
    expect(AGENT_STATUS_META.working.label).toBe('工作中');
  });
});
