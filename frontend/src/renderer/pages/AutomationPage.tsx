import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { CalendarClock, FileCog, LoaderCircle, Pause, Play, Plus, Power, RefreshCw, Repeat, Timer, X, Zap } from 'lucide-react';
import { api, relativeTime } from '../services/api';
import GoalsPanel from './GoalsPanel';

interface ScheduleRun { run_id?: string; conversation_id?: string; started_at?: string; status?: string }
interface ScheduledTask {
  id: string;
  name: string;
  description?: string;
  trigger_type: string;
  trigger_args: Record<string, unknown>;
  action: string;
  status?: string;
  goal?: string | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  run_count?: number;
  runs?: ScheduleRun[];
}
interface HubStatus { running?: boolean }
type Freq = 'hours' | 'daily' | 'weekly' | 'event';
type EventKind = 'run.completed' | 'run.failed' | 'file.changed';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
const CRON_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const EVENTS: Record<EventKind, string> = { 'run.completed': '有任务完成时', 'run.failed': '有任务失败时', 'file.changed': '文件夹里的文件变了' };
const RUN_STATUS: Record<string, string> = { completed: '完成', failed: '失败', running: '运行中', cancelled: '已停止' };
const pad = (value: unknown) => String(value ?? 0).padStart(2, '0');

export function describeSchedule(task: Pick<ScheduledTask, 'trigger_type' | 'trigger_args'>): string {
  const args = task.trigger_args ?? {};
  if (task.trigger_type === 'interval') {
    if (args.days) return `每 ${args.days} 天`;
    if (args.hours) return `每 ${args.hours} 小时`;
    if (args.minutes) return `每 ${args.minutes} 分钟`;
    return '按固定间隔';
  }
  if (task.trigger_type === 'cron') {
    const time = args.hour !== undefined ? `${pad(args.hour)}:${pad(args.minute)}` : '';
    const day = typeof args.day_of_week === 'string' ? args.day_of_week : '';
    const index = CRON_DAYS.indexOf(day);
    if (index >= 0) return `每周${WEEKDAYS[index]} ${time}`.trim();
    return time ? `每天 ${time}` : '按计划';
  }
  if (task.trigger_type === 'date') return args.run_date ? `${new Date(String(args.run_date)).toLocaleString()} 执行一次` : '执行一次';
  if (task.trigger_type === 'event') {
    const label = EVENTS[args.event as EventKind] ?? String(args.event ?? '事件');
    const filter = args.filter && typeof args.filter === 'object' ? args.filter as { root?: string; glob?: string } : {};
    return args.event === 'file.changed' && filter.root ? `${label}（${String(filter.root).split(/[\\/]/).pop()}${filter.glob ? ` · ${filter.glob}` : ''}）` : label;
  }
  return task.trigger_type;
}
const taskMessage = (task: ScheduledTask) => task.action?.startsWith('agent:') ? task.action.slice(6) : task.description || task.action;

/**
 * One scheduler for everything timed or event-driven. The optional background host only matters
 * for keeping tasks running after the window closes.
 */
export default function AutomationPage({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const [hub, setHub] = useState<HubStatus | null>(null);
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'tasks' | 'goals'>('tasks');
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({ name: '', message: '', freq: 'daily' as Freq, hours: '4', time: '09:00', weekday: 0, event: 'run.completed' as EventKind, root: '', glob: '' });

  const refresh = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    // The background-host probe can be slow; don't hold the task list for it.
    void api<HubStatus>(apiBaseUrl, '/api/hub/status').catch(() => ({ running: false })).then(setHub);
    try {
      const body = await api<{ tasks: ScheduledTask[] }>(apiBaseUrl, '/api/schedules');
      // Goals live in the same store; they have their own tab.
      const plain = body.tasks.filter((task) => !task.goal);
      setTasks(plain);
      setSelected((current) => current && plain.some((task) => task.id === current) ? current : plain[0]?.id ?? '');
      setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => setConfirmDelete(false), [selected]);

  const act = async (task: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await task(); onToast(done); setError(''); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
    await refresh();
  };
  const create = (event: FormEvent) => {
    event.preventDefault();
    const [hour, minute] = form.time.split(':').map((part) => Number(part) || 0);
    const trigger = form.freq === 'hours'
      ? { trigger_type: 'interval', trigger_args: { hours: Math.max(1, Number(form.hours) || 1) } }
      : form.freq === 'event'
        ? { trigger_type: 'event', trigger_args: { event: form.event, ...(form.event === 'file.changed' ? { filter: { root: form.root.trim(), ...(form.glob.trim() ? { glob: form.glob.trim() } : {}) } } : {}) } }
        : { trigger_type: 'cron', trigger_args: form.freq === 'weekly' ? { day_of_week: CRON_DAYS[form.weekday], hour, minute } : { hour, minute } };
    const id = `task-${Date.now().toString(36)}`;
    void act(async () => {
      await api(apiBaseUrl, '/api/schedules', { method: 'POST', json: { id, name: form.name.trim() || form.message.trim().slice(0, 24), action: `agent:${form.message.trim()}`, ...trigger } });
      setCreating(false);
      setSelected(id);
      setForm({ ...form, name: '', message: '' });
    }, '已创建自动化任务');
  };

  const current = tasks.find((task) => task.id === selected);
  const paused = current?.status === 'paused';
  const needsRoot = form.freq === 'event' && form.event === 'file.changed';

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>自动化</h1><p>让 Atlas 按时、或者在某件事发生时替你做事。</p></div>
      {tab === 'tasks' && <div className="btns">
        <button className="btn ghost" onClick={() => void refresh()} disabled={busy || !connected} aria-label="刷新自动化">{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        <button className="btn primary" disabled={!connected || busy} onClick={() => setCreating(true)}><Plus size={15} />新建任务</button>
      </div>}
    </header>

    <div role="tablist" aria-label="自动化类型" className="mb-4 flex gap-5 shadow-[inset_0_-1px_0_var(--line)]">
      {([['tasks', '定时与触发'], ['goals', '持续目标']] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
        className={tab === id ? 'pb-2.5 text-[13.5px] font-medium text-fg shadow-[inset_0_-2px_0_var(--brand)]' : 'pb-2.5 text-[13.5px] text-fg-3 hover:text-fg'}>{label}</button>)}
    </div>

    {!connected && <div className="error-note">Atlas 后端未连接。</div>}
    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}

    {connected && hub && <div className="card glass" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px', marginBottom: 14 }}>
      <span className={hub.running ? 'ico ether' : 'ico dim'}><Power size={16} /></span>
      <div style={{ flex: 1, fontSize: 13 }}>
        <b style={{ fontWeight: 600 }}>{hub.running ? '后台常驻已开启' : '后台常驻未开启'}</b>
        <div style={{ color: 'var(--ink3)' }}>{hub.running ? '关掉 Atlas 窗口后，定时任务和目标也会照常运行。' : 'Atlas 开着时任务照常运行；想关掉窗口也继续，就打开后台常驻。'}</div>
      </div>
      <button className="btn" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, hub.running ? '/api/hub/stop' : '/api/hub/start', { method: 'POST' }), hub.running ? '已关闭后台常驻' : '已开启后台常驻')}>
        {hub.running ? '关闭' : '开启'}</button>
    </div>}

    {tab === 'goals' && <GoalsPanel apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} />}
    {tab === 'tasks' && <>
      {creating && <form className="card glass form" onSubmit={create}>
        <h2>新建自动化任务</h2>
        <label>要 Atlas 做什么<textarea required autoFocus value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })} placeholder="例如：整理今天 GitHub 上我关注仓库的新 issue，挑出需要我回复的" /></label>
        <div className="two">
          <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="留空则用任务内容开头" /></label>
          <label>什么时候做<select value={form.freq} onChange={(event) => setForm({ ...form, freq: event.target.value as Freq })}>
            <option value="daily">每天</option><option value="weekly">每周</option><option value="hours">每隔几小时</option><option value="event">某件事发生时</option></select></label>
        </div>
        <div className="two">
          {form.freq === 'hours' && <label>间隔（小时）<input type="number" min={1} max={168} value={form.hours} onChange={(event) => setForm({ ...form, hours: event.target.value })} /></label>}
          {(form.freq === 'daily' || form.freq === 'weekly') && <label>时间<input type="time" required value={form.time} onChange={(event) => setForm({ ...form, time: event.target.value })} /></label>}
          {form.freq === 'weekly' && <label>星期<select value={form.weekday} onChange={(event) => setForm({ ...form, weekday: Number(event.target.value) })}>{WEEKDAYS.map((day, index) => <option key={day} value={index}>星期{day}</option>)}</select></label>}
          {form.freq === 'event' && <label>事件<select value={form.event} onChange={(event) => setForm({ ...form, event: event.target.value as EventKind })}>
            {(Object.keys(EVENTS) as EventKind[]).map((kind) => <option key={kind} value={kind}>{EVENTS[kind]}</option>)}</select></label>}
        </div>
        {needsRoot && <div className="two">
          <label>监视的文件夹<input required value={form.root} onChange={(event) => setForm({ ...form, root: event.target.value })} placeholder="D:\项目\docs" /></label>
          <label>只看这些文件（可选）<input value={form.glob} onChange={(event) => setForm({ ...form, glob: event.target.value })} placeholder="*.md" /></label>
        </div>}
        <div className="foot"><button type="button" className="btn ghost" onClick={() => setCreating(false)}>取消</button><button className="btn primary" disabled={busy || !form.message.trim() || (needsRoot && !form.root.trim())}>创建任务</button></div>
      </form>}

      <div className="split">
        <div className="list glass" role="listbox" aria-label="自动化任务">
          {tasks.map((task) => <button className="row" role="option" key={task.id} aria-selected={task.id === selected} onClick={() => setSelected(task.id)}>
            <span className="ico ether">{task.trigger_type === 'event' ? (task.trigger_args?.event === 'file.changed' ? <FileCog size={17} /> : <Zap size={17} />) : task.trigger_type === 'interval' ? <Timer size={17} /> : task.trigger_type === 'cron' ? <Repeat size={17} /> : <CalendarClock size={17} />}</span>
            <span style={{ minWidth: 0 }}><p>{task.name}</p><small>{describeSchedule(task)}，{taskMessage(task)}</small></span>
            <span className="when">{task.status === 'paused' ? <b>已暂停</b> : <b>{task.next_run_at ? relativeTime(task.next_run_at) : task.trigger_type === 'event' ? '等事件' : '—'}</b>}已运行 {task.run_count ?? 0} 次</span>
          </button>)}
          {!tasks.length && <div className="empty"><Repeat size={22} /><b>还没有自动化任务</b>比如「每天 9 点总结昨天的邮件」，或者「docs 里的文件变了就更新目录」。</div>}
        </div>
        {current ? <aside className="detail glass" aria-label="任务详情">
          <h2>{current.name}</h2>
          <div className="sub">{paused ? '已暂停 · ' : ''}{describeSchedule(current)}</div>
          <dl>
            <div><dt>要做的事</dt><dd>{taskMessage(current)}</dd></div>
            {current.trigger_type !== 'event' && <div><dt>下次运行</dt><dd>{current.next_run_at && !paused ? `${new Date(current.next_run_at).toLocaleString()}（${relativeTime(current.next_run_at)}）` : paused ? '暂停中' : '未排期'}</dd></div>}
            <div><dt>上次运行</dt><dd>{current.last_run_at ? `${new Date(current.last_run_at).toLocaleString()}（${relativeTime(current.last_run_at)}）` : '还没运行过'}</dd></div>
          </dl>
          {current.runs && current.runs.length > 0 && <>
            <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>最近运行</h3>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4, fontSize: 12.5 }}>
              {[...current.runs].reverse().slice(0, 8).map((run, index) => <li key={run.run_id ?? index} style={{ display: 'flex', gap: 8 }}>
                <span style={{ color: run.status === 'failed' ? 'var(--danger)' : 'var(--ink2)' }}>{RUN_STATUS[run.status ?? ''] ?? run.status ?? '—'}</span>
                <span style={{ color: 'var(--ink3)' }}>{relativeTime(run.started_at)}</span>
              </li>)}
            </ul>
          </>}
          <div className="btns">
            <button className="btn primary" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, `/api/schedules/${encodeURIComponent(current.id)}/run`, { method: 'POST' }), '已开始运行')}><Play size={14} />立即运行</button>
            <button className="btn ghost" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, `/api/schedules/${encodeURIComponent(current.id)}/${paused ? 'resume' : 'pause'}`, { method: 'POST' }), paused ? '已恢复' : '已暂停')}>{paused ? <Play size={14} /> : <Pause size={14} />}{paused ? '恢复' : '暂停'}</button>
            <button className={`btn ${confirmDelete ? 'danger' : 'ghost'}`} disabled={busy} onClick={() => { if (!confirmDelete) { setConfirmDelete(true); return; } void act(() => api(apiBaseUrl, `/api/schedules/${encodeURIComponent(current.id)}`, { method: 'DELETE' }), '已删除任务'); }}>{confirmDelete ? '确认删除' : '删除'}</button>
          </div>
        </aside> : <div />}
      </div>
    </>}
  </div></div>;
}
