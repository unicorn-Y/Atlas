/**
 * Continuum: a goal-and-attention-driven shell over Atlas's existing runtime.
 * Run lifecycle, approvals, task queues, and computer takeover remain owned by
 * useAtlasStore/backend-adapter. No second WebSocket or optimistic run state.
 */
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import {
  Activity, ArrowLeft, ArrowRight, BookOpen, Bot, ChevronRight,
  CircleAlert, Clock3, Command, Compass, Hand, Layers3,
  LoaderCircle, Maximize2, MessageCircle, Mic, Monitor, PanelRight, Pause, Play,
  Plus, RefreshCw, Search, Send, Settings2, Square, X,
} from 'lucide-react';
import { useAtlasStore } from '../store/useAtlasStore';
import { api, relativeTime } from '../services/api';
import './ContinuumView.css';

type Mode = 'now' | 'overview' | 'focus' | 'memory' | 'environment';
type Kind = 'conversation' | 'project' | 'goal' | 'automation';
type FocusRef = { kind: Kind; id: string };
type Project = { project_id: string; name: string; current_goal?: string; status?: string; updated_at?: string; workspace_path?: string };
type Goal = { id: string; name: string; goal?: string; goal_status?: string; next_run_at?: string; goal_session_id?: string; goal_progress?: { subgoals?: unknown[]; turns_used?: number; max_turns?: number } };
type Automation = { id: string; name: string; enabled?: boolean; status?: string; last_run_at?: string };
type Fact = { key: string; value: string; category: string };
type RunSummary = { run_id: string; conversation_id: string; model: string; status: string; sequence: number; live: boolean; event_count: number; interrupted_by_restart: boolean };
type Row = { ref: FocusRef; title: string; detail: string; status: string; group: string; timestamp?: string };

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
const FOCUS_STORAGE = 'atlas.continuum.focus';
const KIND_LABEL: Record<Kind, string> = { conversation: '对话', project: '项目', goal: '定时目标', automation: '自动化' };
const EVENT_LABEL: Record<string, string> = {
  'run.started': '开始执行', 'run.phase': '进入执行阶段', 'tool.started': '使用工具',
  'tool.completed': '工具执行结束', 'tool.output': '工具输出', 'subtask.started': '创建子任务',
  'subtask.progress': '子任务进展', 'subtask.completed': '子任务完成', 'subtask.output': '子任务输出',
  'approval.required': '等待操作授权', 'input.required': '等待补充信息',
  'run.plan.proposed': '等待计划确认', 'rules.trust_required': '等待信任决定',
  'artifact.updated': '产物已更新', 'run.paused': '任务已暂停', 'run.resumed': '任务已恢复',
  'run.completed': '任务已完成', 'run.failed': '任务失败', 'run.cancelled': '任务已取消',
};
const safeFocus = (): FocusRef | null => {
  try {
    const result = JSON.parse(localStorage.getItem(FOCUS_STORAGE) ?? 'null') as FocusRef | null;
    return result && ['conversation','project','goal','automation'].includes(result.kind) && typeof result.id === 'string' ? result : null;
  } catch { return null; }
};
const displayStatus = (status: string): string => ({
  running: '进行中', planning: '规划中', waiting: '等待处理', paused: '已暂停',
  completed: '已完成', failed: '失败', cancelled: '已取消',
  active: '持续进行', done: '已达成', blocked: '受阻', idle: '空闲',
} as Record<string, string>)[status] ?? status;

export interface ContinuumViewProps {
  onClassic: (view: 'chat' | 'agents' | 'auto' | 'code' | 'memory') => void;
  onSettings: () => void;
  onVoice: () => void;
  conversationSurface: ReactNode;
  onToggleInspector: () => void;
  inspectorOpen: boolean;
}

export default function ContinuumView({ onClassic, onSettings, onVoice, conversationSurface, onToggleInspector, inspectorOpen }: ContinuumViewProps) {
  const connected = useAtlasStore((s) => s.connected);
  const apiBaseUrl = useAtlasStore((s) => s.apiBaseUrl);
  const conversations = useAtlasStore((s) => s.conversations);
  const runs = useAtlasStore((s) => s.runs);
  const activeConversationId = useAtlasStore((s) => s.activeConversationId);
  const storeError = useAtlasStore((s) => s.error);
  const answers = useAtlasStore((s) => s.answers);
  const agents = useAtlasStore((s) => s.agents);
  const takeover = useAtlasStore((s) => s.takeover);
  const deviceError = useAtlasStore((s) => s.devicesError);

  const [mode, setMode] = useState<Mode>('now');
  const [focus, setFocus] = useState<FocusRef | null>(safeFocus);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'active' | 'attention'>('all');
  const [draft, setDraft] = useState('');
  const [projectRows, setProjectRows] = useState<Project[]>([]);
  const [goalRows, setGoalRows] = useState<Goal[]>([]);
  const [automationRows, setAutomationRows] = useState<Automation[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(false);
  const [takeoverBusy, setTakeoverBusy] = useState(false);
  const [agentSelection, setAgentSelection] = useState('');
  const [working, setWorking] = useState(false);
  const [projectConversations, setProjectConversations] = useState<string[] | null>(null);
  const [goalTrace, setGoalTrace] = useState<Array<{ event_id: string; timestamp: string; event: string; data?: Record<string, unknown> }>>([]);
  const [savedRuns, setSavedRuns] = useState<RunSummary[]>([]);
  const [runHistoryOpen, setRunHistoryOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    const [projects, goals, automations, runSummaries] = await Promise.allSettled([
      api<{ projects: Project[] }>(apiBaseUrl, '/api/projects'),
      api<{ goals: Goal[] }>(apiBaseUrl, '/api/goals'),
      api<{ automations: Automation[] }>(apiBaseUrl, '/api/automations'),
      api<{ runs: RunSummary[] }>(apiBaseUrl, '/api/runtime/runs?limit=500'),
    ]);
    if (projects.status === 'fulfilled') setProjectRows(projects.value.projects);
    if (goals.status === 'fulfilled') setGoalRows(goals.value.goals);
    if (automations.status === 'fulfilled') setAutomationRows(automations.value.automations);
    if (runSummaries.status === 'fulfilled') setSavedRuns(runSummaries.value.runs);
    const failed = [projects, goals, automations, runSummaries].filter((result) => result.status === 'rejected');
    setLoadError(failed.length ? `${failed.length} 个数据来源暂时不可用，已保留其他结果。` : '');
    setLoading(false);
  }, [connected, apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!connected) return;
    void useAtlasStore.getState().loadAgents();
  }, [connected]);
  useEffect(() => {
    if (mode === 'environment' && connected) void useAtlasStore.getState().loadTakeoverContext();
    if (mode === 'memory' && connected) {
      void api<Fact[]>(apiBaseUrl, '/api/facts').then(setFacts).catch((error: unknown) => setLoadError(String(error)));
    }
  }, [mode, connected, apiBaseUrl]);
  // Project associations are the explicit IDs returned by the backend.
  useEffect(() => {
    setProjectConversations(null);
    if (!connected || mode !== 'focus' || focus?.kind !== 'project') return;
    let alive = true;
    void api<{ conversation_ids?: string[] }>(apiBaseUrl, `/api/projects/${encodeURIComponent(focus.id)}`)
      .then((result) => { if (alive) setProjectConversations(result.conversation_ids ?? []); })
      .catch(() => { if (alive) { setProjectConversations([]); setLoadError('读取项目关联失败'); } });
    return () => { alive = false; };
  }, [connected, mode, focus?.kind, focus?.id, apiBaseUrl]);
  useEffect(() => {
    setGoalTrace([]);
    if (!connected || mode !== 'focus' || focus?.kind !== 'goal') return;
    let alive = true;
    void api<{ events: Array<{ event_id: string; timestamp: string; event: string; data?: Record<string, unknown> }> }>(apiBaseUrl, `/api/goals/${encodeURIComponent(focus.id)}/trace`)
      .then((result) => { if (alive) setGoalTrace(result.events.slice(-40).reverse()); })
      .catch(() => { if (alive) setLoadError('读取目标历史失败'); });
    return () => { alive = false; };
  }, [connected, mode, focus?.kind, focus?.id, apiBaseUrl]);
  useEffect(() => {
    try { if (focus) localStorage.setItem(FOCUS_STORAGE, JSON.stringify(focus)); else localStorage.removeItem(FOCUS_STORAGE); }
    catch { /* optional local preference */ }
  }, [focus]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key.toLowerCase() === 'j') { event.preventDefault(); setMode('overview'); }
      if (event.altKey && event.key === '/') { event.preventDefault(); setSearchOpen(true); }
      if (event.key === 'Escape') setSearchOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const latest = useMemo(() => {
    const byConversation = new Map<string, (typeof runs)[number]>();
    for (const run of runs) byConversation.set(run.conversationId, run);
    return byConversation;
  }, [runs]);
  const rows = useMemo<Row[]>(() => [
    ...conversations.filter((item) => !item.archived).map((item) => {
      const run = latest.get(item.id);
      return {
        ref: { kind: 'conversation' as const, id: item.id }, title: item.title,
        detail: String(item.preview ?? item.workspace ?? '对话与执行'),
        status: run?.status ?? 'idle', group: KIND_LABEL.conversation, timestamp: item.updated_at,
      };
    }),
    ...projectRows.map((item) => ({ ref: { kind: 'project' as const, id: item.project_id }, title: item.name,
      detail: item.current_goal || item.workspace_path || '项目', status: item.status || 'idle', group: KIND_LABEL.project, timestamp: item.updated_at })),
    ...goalRows.map((item) => ({ ref: { kind: 'goal' as const, id: item.id }, title: item.name,
      detail: item.goal || '持续目标', status: item.goal_status || 'idle', group: KIND_LABEL.goal, timestamp: item.next_run_at })),
    ...automationRows.map((item) => ({ ref: { kind: 'automation' as const, id: item.id }, title: item.name,
      detail: '触发式自动化', status: item.status || (item.enabled ? 'active' : 'paused'), group: KIND_LABEL.automation, timestamp: item.last_run_at })),
  ], [conversations, latest, projectRows, goalRows, automationRows]);
  const attentionRows = rows.filter((item) => ['waiting', 'failed', 'blocked'].includes(item.status));
  const activeRows = rows.filter((item) => ['running', 'planning', 'active'].includes(item.status));
  const filtered = rows.filter((item) => {
    if (filter === 'active' && !activeRows.includes(item)) return false;
    if (filter === 'attention' && !attentionRows.includes(item)) return false;
    return `${item.title} ${item.detail} ${item.group}`.toLowerCase().includes(search.trim().toLowerCase());
  });
  const current = focus && rows.find((item) => item.ref.kind === focus.kind && item.ref.id === focus.id);
  const selectedConversation = focus?.kind === 'conversation' ? conversations.find((item) => item.id === focus.id) : null;
  const selectedRun = selectedConversation ? latest.get(selectedConversation.id) : undefined;
  const persistedForConversation = selectedConversation ? savedRuns.filter((run) => run.conversation_id === selectedConversation.id) : [];
  const selectedEvents = selectedRun?.events ?? [];
  const pending = [...selectedEvents].reverse().find((event) =>
    ['approval.required','input.required','run.plan.proposed','rules.trust_required'].includes(event.type) &&
    !answers[event.id] &&
    !selectedEvents.some((later) => later.sequence > event.sequence && ['approval.responded','run.resumed','tool.started','message.completed','run.completed'].includes(later.type))
  );
  const activeCount = activeRows.length;

  const openFocus = async (ref: FocusRef) => {
    setFocus(ref);
    setMode('focus');
    setRunHistoryOpen(false);
    setSearchOpen(false);
    if (ref.kind === 'conversation') {
      const conversation = conversations.find((item) => item.id === ref.id);
      if (conversation && activeConversationId !== ref.id) await useAtlasStore.getState().openConversation(conversation);
    }
  };
  const createConversation = async () => {
    const before = useAtlasStore.getState().activeConversationId;
    await useAtlasStore.getState().createConversation();
    const id = useAtlasStore.getState().activeConversationId;
    if (id && id !== before) { setFocus({ kind: 'conversation', id }); setMode('focus'); }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || working) return;
    if (focus && focus.kind !== 'conversation' && mode === 'focus') {
      setLoadError('请进入一个关联会话再继续对话；新建独立对话不会自动关联到项目或定时目标。');
      return;
    }
    setWorking(true);
    const text = draft.trim();
    try {
      if (mode !== 'focus' || !selectedConversation) {
        const before = useAtlasStore.getState().activeConversationId;
        await useAtlasStore.getState().createConversation(text.slice(0, 40));
        const id = useAtlasStore.getState().activeConversationId;
        if (!id || id === before) return;
        setFocus({ kind: 'conversation', id });
        setMode('focus');
      } else if (activeConversationId !== selectedConversation.id) {
        await useAtlasStore.getState().openConversation(selectedConversation);
      }
      setDraft('');
      // Runtime stays owned by the existing store; do not hold the input busy for the entire Run.
      void useAtlasStore.getState().sendMessage(text).catch((error: unknown) => setLoadError(String(error)));
    } finally { setWorking(false); }
  };
  const takeoverAction = async (action: 'human_take' | 'agent_take' | 'release') => {
    setTakeoverBusy(true);
    const state = useAtlasStore.getState();
    const holder = state.takeover?.state === 'AGENT' ? state.takeover.holder : null;
    const agentId = action === 'release' ? String(holder ?? '') : agentSelection;
    const granted = await state.takeoverAction(action, { agentId: agentId || undefined });
    await useAtlasStore.getState().loadTakeoverContext();
    if (!granted) setLoadError(useAtlasStore.getState().devicesError || '控制权请求未获确认');
    setTakeoverBusy(false);
  };

  return <div className="continuum" data-testid="continuum-root">
    <header className="continuum-topbar">
      <button className="continuum-brand" onClick={() => { setMode('now'); setFocus(null); }} aria-label="返回 Atlas 此刻">
        <span className="continuum-orb">✦</span><strong>atlas</strong><span className="continuum-edition">CONTINUUM</span>
      </button>
      <div className="continuum-top-actions">
        <span className={`continuum-connection ${connected ? 'online' : ''}`}><span />{connected ? '已连接' : '未连接'}</span>
        <button title="全局关注 Ctrl+J" onClick={() => setMode('overview')}><Layers3 size={18}/><span>全局</span></button>
        <button title="搜索 Alt+/" onClick={() => setSearchOpen(true)}><Search size={18}/></button>
        <button title="语音" onClick={onVoice}><Mic size={18}/></button>
        <button title="设置" onClick={onSettings}><Settings2 size={18}/></button>
        <button className="continuum-classic" title="返回经典界面" onClick={() => onClassic('chat')}>经典界面 <ArrowRight size={15}/></button>
      </div>
    </header>

    <div className={`continuum-body ${mode === 'focus' && selectedConversation ? 'rich' : ''}`}>
      {!connected && <div className="continuum-banner"><CircleAlert size={17}/> Atlas 后端尚未连接。不会显示虚构的真实任务状态；连接后数据自动加载。<button onClick={onSettings}>打开设置</button></div>}
      {(loadError || storeError || deviceError) && <div className="continuum-banner issue"><CircleAlert size={17}/>{loadError || storeError || deviceError}<button onClick={() => setLoadError('')} aria-label="关闭提示"><X size={15}/></button></div>}

      {mode === 'now' && <section className="continuum-now continuum-enter">
        <div className="continuum-sun"><span>✦</span></div>
        <div className="continuum-eyebrow">YOUR PERSONAL INTELLIGENCE</div>
        <h1>此刻，你想推进什么？</h1>
        <p className="continuum-subtitle">交流只是开始。Atlas 可以继续已有目标、执行任务、组织 Agent，并且让你随时介入。</p>
        <div className="continuum-snapshot">
          <button onClick={() => { setMode('overview'); setFilter('active'); }}><Activity size={19}/><strong>{activeCount}</strong><span>进行中的工作</span><ChevronRight size={15}/></button>
          <button onClick={() => { setMode('overview'); setFilter('attention'); }}><CircleAlert size={19}/><strong>{attentionRows.length}</strong><span>需要关注</span><ChevronRight size={15}/></button>
          <button onClick={() => setMode('overview')}><Compass size={19}/><strong>{rows.length}</strong><span>全部工作</span><ChevronRight size={15}/></button>
        </div>
        <div className="continuum-section-line"><span>接着做</span><button onClick={() => setMode('overview')}>查看全部 <ArrowRight size={13}/></button></div>
        <div className="continuum-recent">
          {rows.slice(0, 4).map((item) => <button key={`${item.ref.kind}:${item.ref.id}`} onClick={() => void openFocus(item.ref)}>
            <span className="continuum-icon"><Layers3 size={16}/></span>
            <span><strong>{item.title}</strong><small>{item.group} · {displayStatus(item.status)}</small></span><ChevronRight size={16}/>
          </button>)}
          {!rows.length && <p className="continuum-empty">暂无可显示的工作。可以从下方直接创建新对话。</p>}
        </div>
      </section>}

      {mode === 'overview' && <section className="continuum-panel continuum-enter">
        <div className="continuum-heading"><div><span className="continuum-eyebrow">SITUATIONAL AWARENESS</span><h1>全局关注</h1><p>按实际对象和运行状态组织，不会把项目、会话和定时目标混为同一种任务。</p></div><button onClick={() => void refresh()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''}/>刷新</button></div>
        <div className="continuum-overview-tools">
          <label><Search size={16}/><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索对话、项目、目标、自动化"/></label>
          <div className="continuum-tabs" role="tablist">{(['all','active','attention'] as const).map((key) => <button key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{key === 'all' ? `全部 ${rows.length}` : key === 'active' ? `进行中 ${activeRows.length}` : `需关注 ${attentionRows.length}`}</button>)}</div>
        </div>
        <div className="continuum-list">
          {filtered.map((item) => <button className="continuum-row" key={`${item.ref.kind}:${item.ref.id}`} onClick={() => void openFocus(item.ref)}>
            <span className="continuum-list-symbol">{item.ref.kind === 'conversation' ? <MessageCircle/> : item.ref.kind === 'project' ? <Layers3/> : item.ref.kind === 'goal' ? <Compass/> : <Clock3/>}</span>
            <span className="continuum-row-main"><strong>{item.title}</strong><small>{item.detail}</small></span>
            <span className="continuum-kind">{item.group}</span><span className={`continuum-status ${item.status}`}>{displayStatus(item.status)}</span><span className="continuum-time">{relativeTime(item.timestamp)}</span><ChevronRight size={16}/>
          </button>)}
          {!filtered.length && <div className="continuum-empty">没有符合条件的结果。</div>}
        </div>
      </section>}

      {mode === 'focus' && <section className={`continuum-panel continuum-enter ${selectedConversation ? 'continuum-focus-panel-rich' : ''}`}>
        <button className="continuum-back" onClick={() => setMode('overview')}><ArrowLeft size={15}/> 全局关注</button>
        <div className="continuum-heading"><div><span className="continuum-eyebrow">{focus ? KIND_LABEL[focus.kind] : '当前关注'}</span><h1>{current?.title ?? '未找到这个对象'}</h1><p>{current?.detail ?? '对象可能已被删除或尚未加载。'}</p></div><div className="continuum-focus-actions">{selectedConversation && <button onClick={() => onClassic('chat')}><Maximize2 size={16}/>完整会话</button>}{focus?.kind === 'project' && <button onClick={() => onClassic('code')}>进入项目</button>}{(focus?.kind === 'goal' || focus?.kind === 'automation') && <button onClick={() => onClassic('auto')}>自动化详情</button>}</div></div>
        {selectedConversation ? <div className="continuum-rich-chat">
          <div className="continuum-rich-toolbar">
            <div className="continuum-rich-indicators"><MessageCircle size={15}/><span>完整会话</span>
              {selectedRun && <><span>Run {selectedRun.id.slice(0, 8)}</span><span>{displayStatus(selectedRun.status)}</span></>}
              {pending && <span className="continuum-rich-attention"><CircleAlert size={13}/> {EVENT_LABEL[pending.type]}</span>}
            </div>
            <div className="continuum-rich-controls">
              {selectedRun && ['running', 'paused'].includes(selectedRun.status) && <button disabled={activeConversationId !== selectedConversation.id} onClick={() => useAtlasStore.getState().togglePaused()}>{selectedRun.status === 'paused' ? <Play size={14}/> : <Pause size={14}/>} {selectedRun.status === 'paused' ? '恢复' : '暂停'}</button>}
              {selectedRun && !TERMINAL.has(selectedRun.status) && <button onClick={() => useAtlasStore.getState().stopRun(selectedRun.id)}><Square size={13}/>停止</button>}
              <button onClick={() => setRunHistoryOpen((value) => !value)} aria-expanded={runHistoryOpen}><Clock3 size={15}/> 执行记录 {persistedForConversation.length}</button>
              <button onClick={onToggleInspector} aria-pressed={inspectorOpen}><PanelRight size={15}/> {inspectorOpen ? '收起详情' : '执行详情'}</button>
            </div>
          </div>
          {runHistoryOpen && <div className="continuum-run-history">
            <div><strong>后端运行记录</strong><span>保存的是运行状态和序号；历史工具事件未完整持久化。</span><button onClick={() => void refresh()}><RefreshCw size={13}/>刷新</button></div>
            {persistedForConversation.slice(0,20).map((run) => <div key={run.run_id}>
              <code>{run.run_id.slice(0, 12)}</code>
              <span>{displayStatus(run.status)}</span>
              <span>{run.live ? '后台仍在执行' : run.interrupted_by_restart ? '后端重启中断，需重新执行' : '无当前执行进程'}</span>
              <span>{run.sequence} 条事件序号</span>
            </div>)}
            {!persistedForConversation.length && <p>没有已持久化的运行记录。</p>}
          </div>}
          {conversationSurface}
        </div> : <div className="continuum-object-details">
          <p>此对象是独立的 {focus ? KIND_LABEL[focus.kind] : '资源'}，并非 Run 的别名。下列关联由后端明确提供。</p>
          {focus?.kind === 'project' && <div className="continuum-relations">
            <h3>关联会话</h3>
            {projectConversations === null ? <span>正在读取项目关联…</span> : projectConversations.length === 0 ? <span>暂无可显示的关联会话。</span> : projectConversations.map((id) => {
              const conversation = conversations.find((item) => item.id === id);
              return <button key={id} disabled={!conversation} onClick={() => void openFocus({ kind: 'conversation', id })}>{conversation?.title ?? ('未载入会话 ' + id.slice(0, 8))} <ArrowRight size={14}/></button>;
            })}
          </div>}
          {focus?.kind === 'goal' && <div className="continuum-relations">
            <h3>目标事件</h3>
            {goalRows.find((item) => item.id === focus.id)?.goal_session_id && <small>目标会话：{goalRows.find((item) => item.id === focus.id)?.goal_session_id}</small>}
            {goalTrace.length ? goalTrace.map((item) => <div key={item.event_id}><span>{item.event}</span><small>{new Date(item.timestamp).toLocaleString()}</small></div>) : <span>暂无可显示的事件。</span>}
          </div>}
          <button onClick={() => onClassic(focus?.kind === 'project' ? 'code' : 'auto')}>打开原有管理界面 <ArrowRight size={16}/></button>
        </div>}
      </section>}

      {mode === 'memory' && <section className="continuum-panel continuum-enter"><div className="continuum-heading"><div><span className="continuum-eyebrow">CONTINUITY</span><h1>记忆与知识</h1><p>仅展示后端提供的真实事实。来源和置信度缺失时不自行推断。</p></div><button onClick={() => onClassic('memory')}>完整记忆管理 <ArrowRight size={16}/></button></div><div className="continuum-memory-list">{facts.map((fact) => <div key={fact.key}><BookOpen size={17}/><span><strong>{fact.key}</strong><small>{fact.value}</small></span><em>{fact.category}</em></div>)}{!facts.length && <p className="continuum-empty">暂无可显示的记忆。</p>}</div></section>}

      {mode === 'environment' && <section className="continuum-panel continuum-enter"><div className="continuum-heading"><div><span className="continuum-eyebrow">SHARED ENVIRONMENT</span><h1>电脑控制权</h1><p>控制权属于后端状态机，不随界面切换而改变。</p></div><button onClick={() => void useAtlasStore.getState().loadTakeoverContext()}><RefreshCw size={15}/>刷新</button></div><div className="continuum-takeover"><Monitor size={34}/><span className="continuum-eyebrow">当前状态</span><h2>{takeover?.state === 'HUMAN' ? '由你控制' : takeover?.state === 'AGENT' ? 'Agent 正在控制' : takeover?.state === 'FREE' ? '设备空闲' : '状态尚未加载'}</h2><p>{takeover?.holder ? `持有者：${takeover.holder}` : '没有已确认的持有者'}</p><div>{takeover?.state !== 'HUMAN' && <button onClick={() => void takeoverAction('human_take')} disabled={takeoverBusy || !connected}><Hand size={16}/>我接管</button>}{takeover?.state !== 'AGENT' && <><select value={agentSelection} onChange={(e)=>setAgentSelection(e.target.value)} aria-label="选择 Agent"><option value="">选择 Agent</option>{agents.filter((a)=>a.kind==='persistent').map((a)=><option key={a.id} value={a.id}>{a.name}</option>)}</select><button onClick={() => void takeoverAction('agent_take')} disabled={takeoverBusy || !connected || !agentSelection}><Bot size={16}/>交给 Agent</button></>}{takeover && takeover.state !== 'FREE' && <button onClick={() => void takeoverAction('release')} disabled={takeoverBusy || !connected}>释放控制权</button>}</div></div></section>}
    </div>

    <footer className="continuum-footer">
      <div className="continuum-footer-quick"><button onClick={() => setMode('now')} className={mode==='now'?'current':''}><Compass size={15}/> 此刻</button><button onClick={() => setMode('overview')} className={mode==='overview'?'current':''}><Layers3 size={15}/> 全局关注</button><button onClick={() => setMode('memory')} className={mode==='memory'?'current':''}><BookOpen size={15}/> 记忆</button><button onClick={() => setMode('environment')} className={mode==='environment'?'current':''}><Monitor size={15}/> 环境</button><button onClick={() => void createConversation()}><Plus size={15}/>新对话</button></div>
      {!(mode === 'focus' && selectedConversation) && <form className="continuum-composer" onSubmit={(event)=>void send(event)}><textarea value={draft} onChange={(e)=>setDraft(e.target.value)} placeholder={mode==='focus' && focus?.kind !== 'conversation' ? '切换到会话后可继续向 Atlas 下指令…' : '告诉 Atlas 你想做什么…'} rows={2} onKeyDown={(event)=>{ if(event.key==='Enter'&&!event.shiftKey){event.preventDefault(); event.currentTarget.form?.requestSubmit();}}}/><div><span>{selectedConversation && mode==='focus' ? `继续：${selectedConversation.title}` : '从当前意图开始'}</span><button type="submit" disabled={!connected || !draft.trim() || working || (mode==='focus' && focus?.kind !== 'conversation')} aria-label="发送指令">{working ? <LoaderCircle size={17} className="spin"/>:<Send size={17}/>}</button></div></form>}
    </footer>

    {searchOpen && <div className="continuum-search-scrim" onMouseDown={(e)=>{if(e.target===e.currentTarget)setSearchOpen(false);}} role="presentation"><div className="continuum-search-dialog" role="dialog" aria-label="搜索和切换关注对象"><div><Command size={18}/><input autoFocus placeholder="搜索目标、项目与会话…" value={search} onChange={(e)=>setSearch(e.target.value)}/><button onClick={()=>setSearchOpen(false)} aria-label="关闭搜索"><X size={17}/></button></div>{rows.filter((row) => `${row.title} ${row.detail} ${row.group}`.toLowerCase().includes(search.trim().toLowerCase())).slice(0,12).map((row)=><button key={`${row.ref.kind}:${row.ref.id}`} onClick={()=>void openFocus(row.ref)}><span>{row.title}</span><small>{row.group}</small><ArrowRight size={15}/></button>)}{!filtered.length && <p>未找到结果</p>}</div></div>}
  </div>;
}