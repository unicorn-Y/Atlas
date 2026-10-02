import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { CircleDashed, LoaderCircle, Pause, Pencil, Play, Plus, RefreshCw, Target, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';
import { describeSchedule } from './AutomationPage';

interface Goal {
  id: string;
  name: string;
  goal: string;
  trigger_type: string;
  trigger_args: Record<string, unknown>;
  goal_status?: string;
  goal_progress?: { subgoals?: string[]; turns_used?: number; max_turns?: number; last_verdict?: string; last_reason?: string; paused_reason?: string; last_evaluation?: { reason?: string; verdict?: string } };
  last_run_at?: string | null;
  next_run_at?: string | null;
  run_count?: number;
}
interface GoalEvent { event_id: string; sequence: number; event: string; timestamp: string; data?: Record<string, unknown> }

const STATUS: Record<string, { label: string; tone: string }> = {
  active: { label: '进行中', tone: 'var(--brand)' },
  paused: { label: '已暂停', tone: 'var(--ink3)' },
  done: { label: '已达成', tone: 'var(--ok)' },
  blocked: { label: '卡住了', tone: 'var(--danger)' },
  cleared: { label: '已清除', tone: 'var(--ink3)' },
};
const EVENT: Record<string, string> = {
  'goal.created': '创建目标',
  'goal.replaced': '改了目标',
  'goal.paused': '暂停',
  'goal.resumed': '恢复',
  'goal.triggered': '开始一轮',
  'goal.evaluated': '目标评价',
  'goal.evaluation_failed': '检查未通过',
  'goal.replanned': '重新规划',
  'goal.verified': '目标达成',
  'goal.failed': '执行失败',
  'goal.interrupted': '被中断',
  'goal.retry_requested': '要求重试',
  'goal.continuation_pending': '等待继续',
  'goal.outcome_persist_failed': '结果保存失败',
  'goal.cleared': '清除目标',
  'execution.error': '推进失败',
};
const CRON_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
type Freq = 'hours' | 'daily' | 'weekly';

const eventDetail = (event: GoalEvent) => {
  const data = event.data ?? {};
  const text = data.reason ?? data.detail ?? (typeof data.replan_count === 'number' ? `第 ${data.replan_count} 次重新规划` : '');
  return typeof text === 'string' ? text : '';
};

/** Goals use Hermes lifecycle state and advance when their schedule triggers. */
export default function GoalsPanel({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [selected, setSelected] = useState('');
  const [trace, setTrace] = useState<GoalEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState('');
  const [form, setForm] = useState({ name: '', goal: '', freq: 'hours' as Freq, hours: '2', time: '09:00', weekday: 0 });

  const refresh = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    try {
      const body = await api<{ goals: Goal[] }>(apiBaseUrl, '/api/goals');
      setGoals(body.goals);
      setSelected((current) => current && body.goals.some((goal) => goal.id === current) ? current : body.goals[0]?.id ?? '');
      setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!selected || !connected) { setTrace([]); return; }
    let stale = false;
    api<{ events: GoalEvent[] }>(apiBaseUrl, `/api/goals/${encodeURIComponent(selected)}/trace`)
      .then((body) => { if (!stale) setTrace(body.events.slice().reverse()); })
      .catch(() => { if (!stale) setTrace([]); });
    return () => { stale = true; };
  }, [apiBaseUrl, connected, selected, goals]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    const [hour, minute] = form.time.split(':').map((part) => Number(part) || 0);
    const trigger = form.freq === 'hours'
      ? { trigger_type: 'interval', trigger_args: { hours: Math.max(1, Number(form.hours) || 1) } }
      : { trigger_type: 'cron', trigger_args: form.freq === 'weekly' ? { day_of_week: CRON_DAYS[form.weekday], hour, minute } : { hour, minute } };
    const id = `goal-${Date.now().toString(36)}`;
    setBusy(true);
    try {
      await api(apiBaseUrl, '/api/goals', { method: 'POST', json: { id, name: form.name.trim() || form.goal.trim().slice(0, 24), goal: form.goal.trim(), ...trigger } });
      setCreating(false);
      setSelected(id);
      setForm({ ...form, name: '', goal: '' });
      onToast('已创建目标');
      setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
    await refresh();
  };
  const runNow = async (goal: Goal) => {
    setBusy(true);
    try { await api(apiBaseUrl, `/api/goals/${encodeURIComponent(goal.id)}/run`, { method: 'POST' }); onToast('已开始新一轮'); setError(''); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
    await refresh();
  };

  const act = async (task: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await task(); onToast(done); setError(''); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
    await refresh();
  };
  const current = goals.find((goal) => goal.id === selected);
  const paused = current?.goal_status === 'paused';
  const subgoals = current?.goal_progress?.subgoals ?? [];
  const currentStatus = current?.goal_status === 'paused' && current.goal_progress?.last_verdict === 'blocked'
    ? 'blocked' : current?.goal_status;

  return <>
    <div className="btns" style={{ justifyContent: 'flex-end', marginBottom: 12 }}>
      <button className="btn ghost" onClick={() => void refresh()} disabled={busy || !connected} aria-label="刷新目标">{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
      <button className="btn primary" disabled={!connected || busy} onClick={() => setCreating(true)}><Plus size={15} />新建目标</button>
    </div>
    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}

    {creating && <form className="card glass form" onSubmit={(event) => void create(event)}>
      <h2>新建持续目标</h2>
      <label>要达成的结果<textarea required autoFocus value={form.goal} onChange={(event) => setForm({ ...form, goal: event.target.value })} placeholder="写清楚怎样算完成，例如：让 Atlas 仓库的前端测试全部通过，并且 npm run build 成功" /></label>
      <div className="two">
        <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="留空则用目标开头" /></label>
        <label>多久推进一轮<select value={form.freq} onChange={(event) => setForm({ ...form, freq: event.target.value as Freq })}><option value="hours">每隔几小时</option><option value="daily">每天</option><option value="weekly">每周</option></select></label>
      </div>
      <div className="two">
        {form.freq === 'hours'
          ? <label>间隔（小时）<input type="number" min={1} max={168} value={form.hours} onChange={(event) => setForm({ ...form, hours: event.target.value })} /></label>
          : <label>时间<input type="time" required value={form.time} onChange={(event) => setForm({ ...form, time: event.target.value })} /></label>}
        {form.freq === 'weekly' && <label>星期<select value={form.weekday} onChange={(event) => setForm({ ...form, weekday: Number(event.target.value) })}>{WEEKDAYS.map((day, index) => <option key={day} value={index}>星期{day}</option>)}</select></label>}
      </div>
      <div className="foot"><button type="button" className="btn ghost" onClick={() => setCreating(false)}>取消</button><button className="btn primary" disabled={busy || !form.goal.trim()}>创建目标</button></div>
    </form>}

    <div className="split">
      <div className="list glass" role="listbox" aria-label="持续目标">
        {goals.map((goal) => {
          const value = goal.goal_status === 'paused' && goal.goal_progress?.last_verdict === 'blocked'
            ? 'blocked' : goal.goal_status;
          const status = STATUS[value ?? ''] ?? { label: value ?? '未开始', tone: 'var(--ink3)' };
          return <button className="row" role="option" key={goal.id} aria-selected={goal.id === selected} onClick={() => setSelected(goal.id)}>
            <span className="ico ether"><Target size={17} /></span>
            <span style={{ minWidth: 0 }}><p>{goal.name}</p><small>{goal.goal}</small></span>
            <span className="when"><b style={{ color: status.tone }}>{status.label}</b>已推进 {goal.run_count ?? 0} 轮</span>
          </button>;
        })}
        {!goals.length && <div className="empty"><Target size={22} /><b>还没有持续目标</b>目标会一轮轮推进，直到 Atlas 检查确认完成。比如「让测试全部通过」。</div>}
      </div>
      {current ? <aside className="detail glass" aria-label="目标详情">
        <h2>{current.name}</h2>
        <div className="sub">{STATUS[currentStatus ?? '']?.label ?? '未开始'}，{describeSchedule(current)}推进一轮</div>
        <dl>
          <div><dt>目标</dt><dd>{editing
            ? <form onSubmit={(event) => { event.preventDefault(); const goal = editing.trim(); if (goal) void act(() => api(apiBaseUrl, `/api/goals/${encodeURIComponent(current.id)}`, { method: 'PUT', json: { goal } }), '目标已更新，会从头重新推进').then(() => setEditing('')); }}>
              <textarea autoFocus value={editing} onChange={(event) => setEditing(event.target.value)} rows={3} style={{ width: '100%' }} />
              <div className="btns"><button className="btn primary" disabled={busy || !editing.trim()}>保存</button><button type="button" className="btn ghost" onClick={() => setEditing('')}>取消</button></div>
            </form>
            : current.goal}</dd></div>
          {(current.goal_progress?.last_reason || (currentStatus === 'blocked' && current.goal_progress?.paused_reason)) && <div><dt>{currentStatus === 'blocked' ? '卡住原因' : '上次评价'}</dt><dd>{currentStatus === 'blocked' ? current.goal_progress?.paused_reason : current.goal_progress?.last_reason}</dd></div>}
          {current.goal_progress && <div><dt>推进轮数</dt><dd>{current.goal_progress.turns_used ?? 0} / {current.goal_progress.max_turns ?? 20}</dd></div>}
          <div><dt>下一轮</dt><dd>{current.next_run_at ? `${new Date(current.next_run_at).toLocaleString()}（${relativeTime(current.next_run_at)}）` : '未排期'}</dd></div>
        </dl>
        {subgoals.length > 0 && <>
          <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>检查条件</h3>
          <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6, fontSize: 13 }}>
            {subgoals.map((item, index) => {
              return <li key={`${index}:${item}`} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <CircleDashed size={15} color="var(--ink3)" />
                <span>{item}</span>
              </li>;
            })}
          </ol>
        </>}
        {trace.length > 0 && <>
          <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>推进记录</h3>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6, fontSize: 12.5, maxHeight: 220, overflow: 'auto' }}>
            {trace.slice(0, 40).map((event) => <li key={event.event_id}>
              <b style={{ fontWeight: 500 }}>{EVENT[event.event] ?? event.event}</b>
              <span style={{ color: 'var(--ink3)' }}> · {relativeTime(event.timestamp)}</span>
              {eventDetail(event) && <div style={{ color: 'var(--ink3)' }}>{eventDetail(event)}</div>}
            </li>)}
          </ul>
        </>}
        <div className="btns">
          <button className="btn primary" disabled={busy || paused || currentStatus === 'done' || currentStatus === 'cleared'} onClick={() => void runNow(current)}><Play size={14} />{currentStatus === 'blocked' ? '重试' : '立即推进一轮'}</button>
          <button className="btn ghost" disabled={busy} onClick={() => void act(() => api(apiBaseUrl, `/api/goals/${encodeURIComponent(current.id)}/${paused ? 'resume' : 'pause'}`, { method: 'POST' }), paused ? '已恢复' : '已暂停，不会再自动推进')}>{paused ? <Play size={14} /> : <Pause size={14} />}{paused ? '恢复' : '暂停'}</button>
          {!editing && <button className="btn ghost" disabled={busy} onClick={() => setEditing(current.goal)}><Pencil size={14} />改目标</button>}
        </div>
      </aside> : <div />}
    </div>
  </>;
}
