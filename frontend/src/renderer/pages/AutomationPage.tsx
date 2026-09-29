import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { CalendarClock, LoaderCircle, Play, Plus, Power, RefreshCw, Repeat, Timer, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';

interface HubTask {
  id: string;
  name: string;
  description?: string;
  trigger_type: string;
  trigger_args: Record<string, unknown>;
  action: string;
  status?: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  run_count?: number;
}
interface HubStatus { running?: boolean; scheduler_running?: boolean; task_count?: number }
type Freq = 'hours' | 'daily' | 'weekly';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
const CRON_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const pad = (value: unknown) => String(value ?? 0).padStart(2, '0');

export function describeSchedule(task: Pick<HubTask, 'trigger_type' | 'trigger_args'>): string {
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
  return task.trigger_type;
}
const taskMessage = (task: HubTask) => task.action?.startsWith('agent:') ? task.action.slice(6) : task.description || task.action;

export default function AutomationPage({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const [status, setStatus] = useState<HubStatus | null>(null);
  const [tasks, setTasks] = useState<HubTask[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({ name: '', message: '', freq: 'daily' as Freq, hours: '4', time: '09:00', weekday: 0 });

  const refresh = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    try {
      const next = await api<HubStatus>(apiBaseUrl, '/api/hub/status');
      setStatus(next);
      if (next.running) {
        const body = await api<{ tasks: HubTask[] }>(apiBaseUrl, '/api/hub/tasks');
        setTasks(body.tasks);
        setSelected((current) => current && body.tasks.some((task) => task.id === current) ? current : body.tasks[0]?.id ?? '');
      } else setTasks([]);
      setError('');
    } catch (exc) {
      setStatus({ running: false });
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setBusy(false); }
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
      : { trigger_type: 'cron', trigger_args: form.freq === 'weekly' ? { day_of_week: CRON_DAYS[form.weekday], hour, minute } : { hour, minute } };
    const id = `task-${Date.now().toString(36)}`;
    void act(async () => {
      await api(apiBaseUrl, '/api/hub/tasks', { method: 'POST', json: { id, name: form.name.trim() || form.message.trim().slice(0, 24), message: form.message.trim(), ...trigger } });
      setCreating(false);
      setSelected(id);
      setForm({ ...form, name: '', message: '' });
    }, '已创建自动化任务');
  };

  const running = Boolean(status?.running);
  const current = tasks.find((task) => task.id === selected);

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>自动化</h1><p>让 Atlas 按时替你做事。关掉窗口后任务照常运行，前提是后台服务开着。</p></div>
      <div className="btns">
        <button className="btn ghost" onClick={() => void refresh()} disabled={busy || !connected} aria-label="刷新自动化">{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        {running && <button className="btn" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, '/api/hub/stop', { method: 'POST' }), '后台服务已停止')}><Power size={15} />停止后台服务</button>}
        <button className="btn primary" disabled={!running || busy} onClick={() => setCreating(true)}><Plus size={15} />新建任务</button>
      </div>
    </header>

    {!connected && <div className="error-note">Atlas 后端未连接。</div>}
    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}

    {connected && status && !running && <div className="card glass" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <span className="ico dim"><Power size={18} /></span>
      <div style={{ flex: 1 }}><b style={{ fontWeight: 600 }}>后台服务没有运行</b><div style={{ color: 'var(--ink3)', fontSize: 13 }}>自动化任务靠后台服务按时执行。启动后才能查看和创建任务。</div></div>
      <button className="btn primary" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, '/api/hub/start', { method: 'POST' }), '后台服务已启动')}>{busy ? <LoaderCircle size={15} className="spin" /> : <Power size={15} />}启动后台服务</button>
    </div>}

    {creating && <form className="card glass form" onSubmit={create}>
      <h2>新建自动化任务</h2>
      <label>要 Atlas 做什么<textarea required autoFocus value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })} placeholder="例如：整理今天 GitHub 上我关注仓库的新 issue，挑出需要我回复的" /></label>
      <div className="two">
        <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="留空则用任务内容开头" /></label>
        <label>频率<select value={form.freq} onChange={(event) => setForm({ ...form, freq: event.target.value as Freq })}><option value="daily">每天</option><option value="weekly">每周</option><option value="hours">每隔几小时</option></select></label>
      </div>
      <div className="two">
        {form.freq === 'hours'
          ? <label>间隔（小时）<input type="number" min={1} max={168} value={form.hours} onChange={(event) => setForm({ ...form, hours: event.target.value })} /></label>
          : <label>时间<input type="time" required value={form.time} onChange={(event) => setForm({ ...form, time: event.target.value })} /></label>}
        {form.freq === 'weekly' && <label>星期<select value={form.weekday} onChange={(event) => setForm({ ...form, weekday: Number(event.target.value) })}>{WEEKDAYS.map((day, index) => <option key={day} value={index}>星期{day}</option>)}</select></label>}
      </div>
      <div className="foot"><button type="button" className="btn ghost" onClick={() => setCreating(false)}>取消</button><button className="btn primary" disabled={busy || !form.message.trim()}>创建任务</button></div>
    </form>}

    {running && <div className="split">
      <div className="list glass" role="listbox" aria-label="自动化任务">
        {tasks.map((task) => <button className="row" role="option" key={task.id} aria-selected={task.id === selected} onClick={() => setSelected(task.id)}>
          <span className="ico ether">{task.trigger_type === 'interval' ? <Timer size={17} /> : task.trigger_type === 'cron' ? <Repeat size={17} /> : <CalendarClock size={17} />}</span>
          <span style={{ minWidth: 0 }}><p>{task.name}</p><small>{describeSchedule(task)}，{taskMessage(task)}</small></span>
          <span className="when">{task.status === 'running' ? <span className="live-tag">运行中</span> : <b>{task.next_run_at ? relativeTime(task.next_run_at) : '—'}</b>}已运行 {task.run_count ?? 0} 次</span>
        </button>)}
        {!tasks.length && <div className="empty"><Repeat size={22} /><b>还没有自动化任务</b>比如「每天 9 点总结昨天的邮件」或「每周五整理本周的提交」。</div>}
      </div>
      {current ? <aside className="detail glass" aria-label="任务详情">
        <h2>{current.name}</h2>
        <div className="sub">{describeSchedule(current)}</div>
        <dl>
          <div><dt>要做的事</dt><dd>{taskMessage(current)}</dd></div>
          <div><dt>下次运行</dt><dd>{current.next_run_at ? `${new Date(current.next_run_at).toLocaleString()}（${relativeTime(current.next_run_at)}）` : '未排期'}</dd></div>
          <div><dt>上次运行</dt><dd>{current.last_run_at ? `${new Date(current.last_run_at).toLocaleString()}（${relativeTime(current.last_run_at)}）` : '还没运行过'}</dd></div>
          <div><dt>已运行</dt><dd>{current.run_count ?? 0} 次</dd></div>
        </dl>
        <div className="btns">
          <button className="btn primary" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, `/api/hub/tasks/${encodeURIComponent(current.id)}/run`, { method: 'POST' }), '已开始运行')}><Play size={14} />立即运行</button>
          <button className={`btn ${confirmDelete ? 'danger' : 'ghost'}`} disabled={busy} onClick={() => { if (!confirmDelete) { setConfirmDelete(true); return; } void act(() => api(apiBaseUrl, `/api/hub/tasks/${encodeURIComponent(current.id)}`, { method: 'DELETE' }), '已删除任务'); }}>{confirmDelete ? '确认删除' : '删除'}</button>
        </div>
      </aside> : <div />}
    </div>}
  </div></div>;
}
