import { useEffect, useMemo, useState } from 'react';
import {
  Activity, Bot, MessageSquare, Monitor, Pencil, Plus, Puzzle, Radio, RefreshCw,
  Repeat, HeartPulse, Trash2, UserCog, X, type LucideIcon,
} from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import type { PersistentAgentRecord } from '../../services/persistentApi';
import { Button } from '../../ui/Button';
import { Dialog } from '../../ui/Dialog';
import { cn } from '../../ui/cn';
import AgentChatTab from './AgentChatTab';
import AgentIdentityTab from './AgentIdentityTab';
import AgentSkillsTab from './AgentSkillsTab';
import AgentChannelsTab from './AgentChannelsTab';
import AgentHeartbeatTab from './AgentHeartbeatTab';
import AgentAutomationsTab from './AgentAutomationsTab';
import AgentComputerTab from './AgentComputerTab';
import AgentActivityTab from './AgentActivityTab';
import { field, fieldArea, AgentMarkers, StatusBadge } from './shared';

type AgentTab = 'chat' | 'identity' | 'skills' | 'channels' | 'heartbeat' | 'automations' | 'computer' | 'activity';
const TABS: Array<[AgentTab, string, LucideIcon]> = [
  ['chat', '聊天', MessageSquare],
  ['identity', '身份·模型', UserCog],
  ['skills', 'Skills', Puzzle],
  ['channels', 'Channels', Radio],
  ['heartbeat', 'Heartbeat', HeartPulse],
  ['automations', 'Automations', Repeat],
  ['computer', '电脑', Monitor],
  ['activity', 'Activity', Activity],
];

interface AgentFormState { name: string; description: string; model: string; reasoning: string; instructions: string; workspace: string }
const EMPTY_FORM: AgentFormState = { name: '', description: '', model: '', reasoning: '', instructions: '', workspace: '' };

/** Agents 面板：花名册（persistent + 内置角色分组）+ 八个详情 tab。 */
export default function AgentsPage({ apiBaseUrl, connected, onToast, username }: {
  apiBaseUrl: string; connected: boolean; onToast: (text: string) => void; username: string;
}) {
  const agents = useAtlasStore((state) => state.agents);
  const loading = useAtlasStore((state) => state.agentsLoading);
  const error = useAtlasStore((state) => state.agentsError);
  const loadAgents = useAtlasStore((state) => state.loadAgents);
  const createAgent = useAtlasStore((state) => state.createAgent);
  const updateAgent = useAtlasStore((state) => state.updateAgent);
  const deleteAgent = useAtlasStore((state) => state.deleteAgent);
  const setAgentEnabled = useAtlasStore((state) => state.setAgentEnabled);

  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState<AgentTab>('chat');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<AgentFormState>(EMPTY_FORM);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { void loadAgents(); }, [loadAgents]);
  // 状态是运行投影：页面开着时低频轮询让徽标跟上。
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void loadAgents(); }, 15000);
    return () => window.clearInterval(timer);
  }, [loadAgents]);

  const models = useAtlasStore((state) => state.models);
  const persistent = useMemo(() => agents.filter((agent) => agent.kind === 'persistent'), [agents]);
  const roles = useMemo(() => agents.filter((agent) => agent.kind !== 'persistent'), [agents]);
  const agent = persistent.find((item) => item.id === selected) ?? roles.find((item) => item.id === selected);
  const isRole = Boolean(agent && agent.kind !== 'persistent');

  useEffect(() => { setTab('chat'); setConfirmDelete(false); }, [selected]);
  useEffect(() => {
    if (selected || !persistent.length) return;
    setSelected(persistent[0].id);
  }, [persistent, selected]);

  const openCreate = () => { setForm(EMPTY_FORM); setCreating(true); };
  const openEdit = (record: PersistentAgentRecord) => {
    setForm({
      name: record.name ?? '', description: record.description ?? '', model: record.model ?? '',
      reasoning: record.reasoning_effort ?? '', instructions: record.instructions ?? '',
      workspace: record.agent?.workspace ?? '',
    });
    setEditing(true);
  };
  const submit = async () => {
    setBusy(true);
    const payload = {
      ...(form.name.trim() ? { name: form.name.trim() } : {}),
      description: form.description.trim(),
      model: form.model, reasoning_effort: form.reasoning, instructions: form.instructions,
      agent: { workspace: form.workspace.trim() },
    };
    const result = creating ? await createAgent({ ...payload, kind: 'persistent' }) : agent ? await updateAgent(agent.id, payload) : null;
    setBusy(false);
    if (!result) { onToast(useAtlasStore.getState().agentsError || '没有保存成功'); return; }
    setCreating(false); setEditing(false);
    setSelected(result.id);
    onToast(creating ? `Agent「${result.name}」已创建` : '已保存');
  };
  const remove = async () => {
    if (!agent) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    if (await deleteAgent(agent.id)) { setSelected(''); onToast('Agent 已删除'); }
  };

  const formBody = <form className="grid gap-3.5" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    <label className="grid gap-1 text-[13px] text-fg-2">名字
      <input autoFocus required value={form.name} disabled={Boolean(agent)} onChange={(event) => setForm({ ...form, name: event.target.value })}
        placeholder="比如：research-rabbit" className={field} />
    </label>
    <label className="grid gap-1 text-[13px] text-fg-2">一句话职责
      <input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })}
        placeholder="它负责什么、边界在哪" className={field} />
    </label>
    <div className="grid grid-cols-2 gap-3">
      <label className="grid gap-1 text-[13px] text-fg-2">模型
        <select value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} className={field}>
          <option value="">跟随全局模型</option>
          {models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
        </select>
      </label>
      <label className="grid gap-1 text-[13px] text-fg-2">推理档位
        <select value={form.reasoning} onChange={(event) => setForm({ ...form, reasoning: event.target.value })} className={field}>
          <option value="">默认</option>
          {(['minimal', 'low', 'medium', 'high'] as const).map((effort) => <option key={effort} value={effort}>{effort}</option>)}
        </select>
      </label>
    </div>
    <label className="grid gap-1 text-[13px] text-fg-2">常驻指令（它的长期记忆和做事方式）
      <textarea rows={5} value={form.instructions} onChange={(event) => setForm({ ...form, instructions: event.target.value })}
        placeholder="你是…，你永远…，你不…'" className={cn(fieldArea, 'resize-y leading-[1.6]')} />
    </label>
    <label className="grid gap-1 text-[13px] text-fg-2">工作目录（留空跟随主工作区）
      <input value={form.workspace} onChange={(event) => setForm({ ...form, workspace: event.target.value })}
        placeholder="D:\some\folder" className={cn(field, 'font-mono text-[12.5px]')} />
    </label>
    <div className="flex justify-end gap-2">
      <Button variant="ghost" onClick={() => { setCreating(false); setEditing(false); }}>取消</Button>
      <Button type="submit" variant="primary" disabled={busy || !form.name.trim()}>{creating ? '创建' : '保存'}</Button>
    </div>
  </form>;

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>Agents</h1><p>常驻的干系人：每个都有自己的模型、指令、技能和心跳，可以挂到渠道和自动化上。</p></div>
      <div className="btns">
        <button className="btn ghost" onClick={() => void loadAgents()} disabled={loading} aria-label="刷新 Agents">{loading ? <RefreshCw size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        <button className="btn primary" disabled={!connected} onClick={openCreate}><Plus size={15} />新建 Agent</button>
      </div>
    </header>

    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => void loadAgents()}><X size={15} /></button></div>}
    {!connected && <div className="error-note">Atlas 后端未连接，列表可能不是最新的。</div>}

    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] lg:items-start">
      <div className="grid gap-4">
        <section aria-label="常驻 Agent 列表">
          <h2 className="m-0 px-1 pb-1.5 text-[12px] font-normal text-fg-3">Agents</h2>
          <div className="list glass">
            {persistent.map((item) => <button key={item.id} className="row" aria-selected={item.id === selected} onClick={() => setSelected(item.id)}>
              <span className="ico ether"><Bot size={17} /></span>
              <span style={{ minWidth: 0 }}>
                <p>{item.name}</p>
                <small className="flex items-center gap-2"><StatusBadge status={item.status} />{item.model && <span className="truncate">{item.model}</span>}</small>
              </span>
              <span className="when"><AgentMarkers agent={item} /></span>
            </button>)}
            {!persistent.length && <div className="empty py-7"><Bot size={20} /><b>还没有常驻 Agent</b>点右上角「新建 Agent」造一个。</div>}
          </div>
        </section>
        <section aria-label="内置角色">
          <h2 className="m-0 px-1 pb-1.5 text-[12px] font-normal text-fg-3">角色（内置，不可升级）</h2>
          <div className="list glass">
            {roles.map((item) => <button key={item.id} className="row off" aria-selected={item.id === selected} onClick={() => setSelected(item.id)}>
              <span className="ico dim"><UserCog size={17} /></span>
              <span style={{ minWidth: 0 }}><p>{item.name}</p><small>{item.description || '内置角色'}</small></span>
            </button>)}
          </div>
        </section>
      </div>

      {agent && !isRole ? <section className="min-w-0 rounded-xl glass" aria-label={`${agent.name} 详情`}>
        <header className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5">
          <Bot size={18} className="shrink-0 text-brand" />
          <b className="text-[16px] font-semibold text-heading">{agent.name}</b>
          <StatusBadge status={agent.status} />
          {agent.agent?.enabled === false && <span className="rounded-full bg-danger-soft px-2 py-0.5 text-[11.5px] text-danger">已停用</span>}
          <span className="flex-1" />
          <label className="flex items-center gap-1.5 text-[12.5px] text-fg-3">
            <input type="checkbox" checked={agent.agent?.enabled !== false} onChange={(event) => void setAgentEnabled(agent.id, event.target.checked)} />启用
          </label>
          <Button size="sm" variant="ghost" onClick={() => openEdit(agent)}><Pencil />编辑</Button>
          <Button size="sm" variant={confirmDelete ? 'danger' : 'ghost'} onClick={() => void remove()}>{confirmDelete ? '确认删除' : <><Trash2 />删除</>}</Button>
        </header>
        <div role="tablist" aria-label={`${agent.name} 的页面`} className="flex gap-4 overflow-x-auto px-5 shadow-[inset_0_-1px_0_var(--line)]">
          {TABS.map(([id, label, Icon]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={cn('flex shrink-0 items-center gap-1.5 py-2.5 text-[13px]', tab === id ? 'font-medium text-fg shadow-[inset_0_-2px_0_var(--brand)]' : 'text-fg-3 hover:text-fg')}>
            <Icon size={14} />{label}
          </button>)}
        </div>
        <div className="min-w-0 p-5">
          {tab === 'chat' && <AgentChatTab agent={agent} username={username} />}
          {tab === 'identity' && <AgentIdentityTab agent={agent} />}
          {tab === 'skills' && <AgentSkillsTab apiBaseUrl={apiBaseUrl} agent={agent} onToast={onToast} />}
          {tab === 'channels' && <AgentChannelsTab apiBaseUrl={apiBaseUrl} agent={agent} onToast={onToast} />}
          {tab === 'heartbeat' && <AgentHeartbeatTab apiBaseUrl={apiBaseUrl} agent={agent} onToast={onToast} />}
          {tab === 'automations' && <AgentAutomationsTab agent={agent} onToast={onToast} />}
          {tab === 'computer' && <AgentComputerTab agent={agent} onToast={onToast} />}
          {tab === 'activity' && <AgentActivityTab apiBaseUrl={apiBaseUrl} agent={agent} />}
        </div>
      </section>
      : agent && isRole ? <section className="rounded-xl glass p-6" aria-label={`${agent.name} 角色`}>
        <h2 className="m-0 mb-1 flex items-center gap-2 text-[19px] font-semibold text-heading"><UserCog size={18} className="text-fg-3" />{agent.name}</h2>
        <p className="mt-0 mb-4 text-[13px] text-fg-3">{agent.description || '内置角色：一次性的任务模板，跑完即走，不常驻。'}</p>
        <dl className="m-0 grid gap-3 text-[13px]">
          {agent.model && <div><dt className="text-[12px] text-fg-3">模型</dt><dd className="m-0">{agent.model}</dd></div>}
          {agent.reasoning_effort && <div><dt className="text-[12px] text-fg-3">推理档位</dt><dd className="m-0">{agent.reasoning_effort}</dd></div>}
          {agent.instructions && <div><dt className="text-[12px] text-fg-3">指令</dt><dd className="m-0 whitespace-pre-wrap leading-[1.7]">{agent.instructions}</dd></div>}
        </dl>
        <p className="mt-5 mb-0 rounded-xl bg-sunken px-3.5 py-2.5 text-[12.5px] leading-[1.6] text-fg-3">
          角色不能升级为常驻 Agent，也不参与心跳、渠道和自动化。要改它的指令或模型，去「设置 → 角色」。
        </p>
      </section>
      : <section className="grid place-items-center rounded-xl glass py-20 text-[13.5px] text-fg-3">
        {loading ? '正在读取 Agents…' : '选一个 Agent 看详情，或新建一个。'}
      </section>}
    </div>

    <Dialog open={creating || editing} onOpenChange={(open) => { if (!open) { setCreating(false); setEditing(false); } }} label={creating ? '新建 Agent' : '编辑 Agent'}
      className="flex h-[min(680px,calc(100vh-48px))] w-[min(560px,calc(100vw-32px))] flex-col">
      <div className="min-h-0 flex-1 overflow-auto px-6 pt-6">
        <h3 className="m-0 mb-1 text-[17px] font-semibold text-heading">{creating ? '新建常驻 Agent' : `编辑 ${agent?.name ?? ''}`}</h3>
        <p className="mt-1 mb-5 text-[12.5px] text-fg-3">{creating ? '名字是它的身份证（小写字母、数字、连字符）。' : '名字创建后不能改。'}</p>
        {formBody}
      </div>
    </Dialog>
  </div></div>;
}
