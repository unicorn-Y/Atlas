import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutomationRecord, DeviceRecord, PersistentAgentRecord } from '../../services/persistentApi';

/**
 * zustand v5 的服务端渲染走 getInitialState（拿不到 setState 后的值），
 * 所以直接把 store 模块换成「可变 fixture」：hook 按 selector 读，getState 返回同一份。
 */
const state: Record<string, unknown> = {};
vi.mock('../../store/useAtlasStore', () => {
  const hook = Object.assign(
    (selector: (current: Record<string, unknown>) => unknown) => selector(state),
    {
      getState: () => state,
      setState: (patch: Record<string, unknown> | ((current: Record<string, unknown>) => Record<string, unknown>)) =>
        Object.assign(state, typeof patch === 'function' ? patch(state) : patch),
    },
  );
  return { useAtlasStore: hook, backend: { apiBaseUrl: 'http://test' } };
});

const { default: AgentsPage } = await import('./AgentsPage');
const { default: GroupsView } = await import('../GroupsView');
const { default: DevicesPage } = await import('../DevicesPage');

const agent = (patch: Partial<PersistentAgentRecord>): PersistentAgentRecord => ({
  id: 'rabbit', name: 'research-rabbit', kind: 'persistent', model: 'glm-4.7', status: 'idle',
  agent: { enabled: true, heartbeat: { enabled: true, interval_minutes: 30, active_hours: '', prompt: '', delivery: 'owner', isolated_session: true }, channels: [{ channel: 'telegram', target: '1' }] },
  ...patch,
});
const automation: AutomationRecord = {
  id: 'job-1', name: '晨报', enabled: true, owner_agent_id: 'rabbit',
  trigger: { kind: 'cron', cron_expr: '0 9 * * *' }, payload: { kind: 'agent_turn', message: '写晨报' }, delivery: { mode: 'none' },
};
const device: DeviceRecord = { id: 'atlas-laptop', display_name: 'This PC', kind: 'atlas-laptop', online: true, trusted: true };

const noop = () => undefined;
beforeEach(() => {
  for (const key of Object.keys(state)) delete state[key];
  Object.assign(state, {
    models: [],
    agents: [agent({}), agent({ id: 'default', name: 'default', kind: 'role', status: undefined, agent: undefined })],
    agentsLoading: false, agentsError: null,
    loadAgents: noop, createAgent: noop, updateAgent: noop, deleteAgent: noop, setAgentEnabled: noop,
    conversations: [], conversationsLoading: true, conversationMessages: {}, activeConversationId: '', runs: [], busy: false, sendMessage: noop,
    groups: [], groupsAvailable: false, groupsLoading: false, groupsError: null, groupTimelines: {}, groupBusy: {},
    loadAgentsGroups: noop,
    loadGroups: noop, createGroup: noop, deleteGroup: noop, sendGroupTurn: noop, loadGroupTimeline: noop, stopGroup: noop,
    devices: [device], selfDeviceId: 'atlas-laptop', devicesLoading: false, devicesError: null,
    takeover: null, deviceActivity: [], handoffCards: [],
    loadDevices: noop, patchDevice: noop, removeDevice: noop, registerDevice: noop,
    takeoverAction: noop, loadTakeoverContext: noop, handoffAction: noop,
    automations: [automation], automationsLoading: false, automationsError: null, automationRuns: {},
    loadAutomations: noop,
  });
});

describe('AgentsPage', () => {
  it('splits persistent agents from built-in roles and marks roles as non-upgradable', () => {
    const html = renderToStaticMarkup(<AgentsPage apiBaseUrl="http://test" connected onToast={noop} username="Tester" />);
    expect(html).toContain('research-rabbit');
    expect(html).toContain('角色（内置，不可升级）');
    expect(html).toContain('空闲');
    expect(html).toContain('心跳已开启'); // heartbeat marker on the roster row
    expect(html).not.toContain('新建常驻 Agent'); // dialog starts closed
  });

  it('shows the empty state while there are no agents', () => {
    Object.assign(state, { agents: [] });
    const html = renderToStaticMarkup(<AgentsPage apiBaseUrl="http://test" connected onToast={noop} username="Tester" />);
    expect(html).toContain('还没有常驻 Agent');
  });
});

describe('GroupsView', () => {
  it('degrades to the placeholder when the W8 backend is not mounted (404)', () => {
    const html = renderToStaticMarkup(<GroupsView onToast={noop} />);
    expect(html).toContain('群聊服务未就绪');
    expect(html).not.toContain('新建群聊');
  });

  it('renders the roster once groups exist (detail opens on click, needs hydration)', () => {
    Object.assign(state, {
      groupsAvailable: true,
      groups: [{ id: 'g1', name: '项目评审室', members: [{ agent_id: 'rabbit' }] }],
      groupTimelines: { g1: [{ actor_kind: 'user', actor: 'user', text: '开始吧' }] },
    });
    const html = renderToStaticMarkup(<GroupsView onToast={noop} />);
    expect(html).toContain('项目评审室');
    expect(html).not.toContain('群聊服务未就绪'); // placeholder hidden once the backend answers
  });
});

describe('DevicesPage', () => {
  it('renders the takeover block and the self atlas-laptop badge', () => {
    const html = renderToStaticMarkup(<DevicesPage onToast={noop} />);
    expect(html).toContain('电脑控制权');
    expect(html).toContain('本机 · atlas-laptop');
    expect(html).toContain('登记一台入口设备');
  });

  it('shows handoff cards and agent control state', () => {
    Object.assign(state, {
      takeover: { device_id: 'atlas-laptop', state: 'AGENT', holder: 'rabbit', since_ts: Date.now() / 1000 },
      handoffCards: [{ card_id: 'c1', note: '帮我确认一下登录验证码', status: 'PENDING', created_ts: Date.now() / 1000, created_by: 'rabbit' }],
    });
    const html = renderToStaticMarkup(<DevicesPage onToast={noop} />);
    expect(html).toContain('Agent 在控制');
    expect(html).toContain('帮我确认一下登录验证码');
    expect(html).toContain('办好了');
  });
});
