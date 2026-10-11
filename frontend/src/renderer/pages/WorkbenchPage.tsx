import { useCallback, useEffect, useMemo, useState } from 'react';
import { Blocks, LoaderCircle, MessageSquare, Plus, Power, Settings2, SquareTerminal, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import { relativeTime } from '../services/api';
import { workbenchApi, type HistoryItem, type SessionSnapshot, type WorkbenchAgent } from '../services/workbenchApi';
import AgentChat from './workbench/AgentChat';
import AgentTerminal from './workbench/AgentTerminal';
import AgentSettings from './workbench/AgentSettings';
import AddAgentDialog from './workbench/AddAgentDialog';

const MODE_BADGE = { acp: 'ACP', terminal: '终端', command: '命令' } as const;
const readSelected = () => { try { return localStorage.getItem('atlas.workbench.selected') ?? ''; } catch { return ''; } };
const writeSelected = (value: string) => { try { localStorage.setItem('atlas.workbench.selected', value); } catch { /* storage unavailable */ } };

/**
 * 工作台：挂在 Atlas 主体外面的独立 agent（挂件）。每个挂件独立进程、独立文件夹、独立配置，
 * 不接 Atlas 的记忆和工具；主体的改动不会碰到它们。
 */
export default function WorkbenchPage({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const api = useMemo(() => workbenchApi(apiBaseUrl), [apiBaseUrl]);
  const [agents, setAgents] = useState<WorkbenchAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(readSelected);
  const [adding, setAdding] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [running, setRunning] = useState<SessionSnapshot[]>([]);
  const [activeSession, setActiveSession] = useState<Record<string, string>>({});
  const [panel, setPanel] = useState<'chat' | 'shell'>('chat');
  const [starting, setStarting] = useState(false);
  /** Terminals stay mounted once opened so switching agents does not kill them. */
  const [openTerminals, setOpenTerminals] = useState<string[]>([]);

  const refresh = useCallback(() => api.agents().then((data) => setAgents(data.agents)).catch((cause: Error) => onToast(cause.message)).finally(() => setLoading(false)), [api]);
  useEffect(() => { if (connected) void refresh(); }, [connected, refresh]);

  const agent = agents.find((item) => item.id === selected) ?? agents[0];
  useEffect(() => { if (agent && agent.id !== selected) setSelected(agent.id); }, [agent?.id]);
  useEffect(() => { if (selected) writeSelected(selected); setPanel('chat'); }, [selected]);

  const refreshSessions = useCallback(() => {
    if (!agent || agent.mode === 'terminal') { setHistory([]); setRunning([]); return; }
    void api.sessions(agent.id).then((data) => { setHistory(data.history); setRunning(data.running); }).catch(() => undefined);
  }, [api, agent?.id, agent?.mode]);
  useEffect(refreshSessions, [refreshSessions]);

  useEffect(() => {
    if (agent?.mode === 'terminal' && agent.enabled && !openTerminals.includes(agent.id)) setOpenTerminals((list) => [...list, agent.id]);
  }, [agent?.id, agent?.mode, agent?.enabled, agent?.updated_at, openTerminals]);

  const sessionId = agent ? activeSession[agent.id] ?? running[0]?.id ?? history[0]?.id : undefined;

  const newSession = async () => {
    if (!agent) return;
    setStarting(true);
    try {
      const snap = await api.start(agent.id);
      setActiveSession((map) => ({ ...map, [agent.id]: snap.id }));
      setPanel('chat');
      refreshSessions(); void refresh();
    } catch (cause) { onToast((cause as Error).message); }
    finally { setStarting(false); }
  };

  const toggleEnabled = async () => {
    if (!agent) return;
    try { const next = await api.setEnabled(agent.id, !agent.enabled); setAgents((list) => list.map((item) => item.id === next.id ? next : item)); }
    catch (cause) { onToast((cause as Error).message); }
  };

  const removeSession = async (id: string) => {
    if (!agent) return;
    try { await api.deleteSession(agent.id, id); setActiveSession((map) => { const next = { ...map }; if (next[agent.id] === id) delete next[agent.id]; return next; }); refreshSessions(); }
    catch (cause) { onToast((cause as Error).message); }
  };

  const runningIds = new Set(running.map((item) => item.id));

  return <div className="screen page"><div className="flex h-full min-h-0 gap-4 p-4">
    <aside className="flex w-60 shrink-0 flex-col gap-2">
      <div className="flex items-center gap-2 px-1">
        <Blocks size={17} className="text-brand" />
        <h1 className="m-0 flex-1 text-[15px] font-semibold text-heading">工作台</h1>
        <Button size="sm" variant="secondary" onClick={() => setAdding(true)} disabled={!connected}><Plus />添加</Button>
      </div>
      <p className="m-0 px-1 text-[11.5px] leading-relaxed text-fg-3">挂在主体外面的独立 agent。各自独立进程、独立文件夹和配置，不接 Atlas 的记忆和工具，互不影响。</p>
      <div className="grid min-h-0 flex-1 content-start gap-1 overflow-auto">
        {loading && <p className="m-0 flex items-center gap-2 px-2 text-[12.5px] text-fg-3"><LoaderCircle size={13} className="animate-spin" />加载中…</p>}
        {!loading && !agents.length && <div className="rounded-xl bg-sunken p-3 text-[12.5px] text-fg-2">还没有挂件。点「添加」从 ACP 注册表装一个（Claude、Codex、Gemini、OpenCode 等 40 多个），或者挂你自己的。</div>}
        {agents.map((item) => <button key={item.id} onClick={() => setSelected(item.id)}
          className={cn('flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-left', item.id === agent?.id ? 'bg-selected' : 'hover:bg-hover', !item.enabled && 'opacity-50')}>
          {item.icon ? <img src={item.icon} alt="" className="size-7 shrink-0 rounded-lg bg-white p-0.5" /> : <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand-soft text-[12px] font-semibold text-brand">{item.name.slice(0, 1)}</span>}
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-fg">{item.name}</span>
            <span className="block truncate text-[11.5px] text-fg-3">{item.description || item.command}</span>
          </span>
          <span className="shrink-0 rounded-md bg-sunken px-1 text-[10.5px] text-fg-3">{MODE_BADGE[item.mode]}</span>
          {item.running > 0 && <span className="size-1.5 shrink-0 rounded-full bg-ok" title={`${item.running} 个会话在运行`} />}
        </button>)}
      </div>
    </aside>

    <section className="flex min-w-0 flex-1 flex-col rounded-2xl card-surface p-4">
      {!agent ? <div className="grid flex-1 place-items-center text-[13px] text-fg-3">选一个挂件，或者先添加一个。</div> : <>
        <header className="flex flex-wrap items-center gap-2 pb-3 shadow-[inset_0_-1px_0_var(--line)]">
          <div className="min-w-0 flex-1">
            <h2 className="m-0 truncate text-[15px] font-semibold text-heading">{agent.name}
              <span className="ml-2 rounded-md bg-brand-soft px-1.5 py-0.5 align-middle text-[11px] font-normal text-brand">独立 · 无记忆</span></h2>
            <p className="m-0 truncate font-mono text-[11.5px] text-fg-3" title={agent.workspace}>{agent.workspace}</p>
          </div>
          {agent.mode !== 'terminal' && <Button size="sm" variant={panel === 'chat' ? 'secondary' : 'ghost'} onClick={() => setPanel('chat')}><MessageSquare />对话</Button>}
          <Button size="sm" variant={panel === 'shell' ? 'secondary' : 'ghost'} onClick={() => setPanel('shell')} title="在它的工作目录、隔离环境里开 PowerShell：登录、装依赖、看文件"><SquareTerminal />隔离终端</Button>
          {agent.mode !== 'terminal' && <Button size="sm" variant="primary" disabled={!agent.enabled || starting} onClick={() => void newSession()}>{starting ? <LoaderCircle className="animate-spin" /> : <Plus />}新会话</Button>}
          <Button size="icon-sm" variant="ghost" aria-label={agent.enabled ? '停用' : '启用'} title={agent.enabled ? '停用（结束它的所有会话）' : '启用'} onClick={() => void toggleEnabled()}><Power className={agent.enabled ? 'text-ok' : undefined} /></Button>
          <Button size="icon-sm" variant="ghost" aria-label="设置" onClick={() => setSettingsOpen(true)}><Settings2 /></Button>
        </header>

        <div className="relative min-h-0 flex-1 pt-3">
          {panel === 'shell' && <div className="absolute inset-0 pt-3"><AgentTerminal key={`shell-${agent.id}`} url={api.terminalUrl(agent.id, true)} label={`PowerShell · ${agent.name} 的隔离环境`} active /></div>}
          {openTerminals.map((id) => <div key={id} className={cn('absolute inset-0 pt-3', (panel !== 'chat' || id !== agent.id) && 'invisible')}>
            <AgentTerminal url={api.terminalUrl(id)} label={`${agents.find((a) => a.id === id)?.name ?? id} 的终端界面`} active={panel === 'chat' && id === agent.id} />
          </div>)}
          {panel === 'chat' && agent.mode === 'terminal' && !agent.enabled && <p className="m-0 text-[13px] text-fg-3">这个挂件已停用。</p>}
          {panel === 'chat' && agent.mode !== 'terminal' && <div className="flex h-full min-h-0 gap-3">
            <div className="flex w-48 shrink-0 flex-col gap-1 overflow-auto">
              <p className="m-0 px-1 text-[11.5px] font-semibold text-fg-3">会话</p>
              {!history.length && <p className="m-0 px-1 text-[12px] text-fg-3">还没有会话，点「新会话」。</p>}
              {history.map((item) => <div key={item.id} className={cn('group flex items-center gap-1 rounded-lg px-2 py-1.5', item.id === sessionId ? 'bg-selected' : 'hover:bg-hover')}>
                <button className="min-w-0 flex-1 text-left" onClick={() => setActiveSession((map) => ({ ...map, [agent.id]: item.id }))}>
                  <span className="flex items-center gap-1.5 truncate text-[12.5px] text-fg">{runningIds.has(item.id) && <span className="size-1.5 shrink-0 rounded-full bg-ok" />}<span className="truncate">{item.title}</span></span>
                  <span className="block text-[11px] text-fg-3">{relativeTime(new Date(item.updated_at * 1000).toISOString())}</span>
                </button>
                <button aria-label="删除会话" onClick={() => void removeSession(item.id)} className="hidden size-6 shrink-0 place-items-center rounded-md text-fg-3 group-hover:grid hover:text-danger"><Trash2 size={13} /></button>
              </div>)}
            </div>
            <div className="min-w-0 flex-1">
              {sessionId
                ? <AgentChat key={`${agent.id}-${sessionId}`} api={api} agent={agent} sessionId={sessionId} onToast={onToast} onSessionsChanged={refreshSessions} />
                : <div className="grid h-full place-items-center text-center text-[13px] text-fg-3"><div>
                    <p className="m-0">{agent.description || '一个独立的 agent。'}</p>
                    <Button className="mt-3" variant="primary" disabled={!agent.enabled || starting} onClick={() => void newSession()}>{starting ? <LoaderCircle className="animate-spin" /> : <Plus />}开始第一个会话</Button>
                  </div></div>}
            </div>
          </div>}
        </div>
      </>}
    </section>

    <AddAgentDialog api={api} open={adding} onOpenChange={setAdding} onToast={onToast}
      onAdded={(next) => { setAgents((list) => [...list.filter((item) => item.id !== next.id), next]); setSelected(next.id); }} />
    {agent && <AgentSettings api={api} agent={agent} open={settingsOpen} onOpenChange={setSettingsOpen} onToast={onToast}
      onChanged={(next) => { setAgents((list) => list.map((item) => item.id === next.id ? next : item)); setOpenTerminals((list) => list.filter((id) => id !== next.id)); refreshSessions(); }}
      onDeleted={() => { setOpenTerminals((list) => list.filter((id) => id !== agent.id)); setSelected(''); void refresh(); }} />}
  </div></div>;
}
