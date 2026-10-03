import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarClock, FileCog, Globe, HeartPulse, LoaderCircle, Pause, Play, Plus, Power,
  RefreshCw, Repeat, Timer, Trash2, Upload, X,
} from 'lucide-react';
import { useAtlasStore } from '../store/useAtlasStore';
import { relativeTime } from '../services/api';
import type { AutomationRecord } from '../services/persistentApi';
import GoalsPanel from './GoalsPanel';
import { describeAutomation, describeTrigger } from './automations/describe';

const RUN_STATUS: Record<string, string> = {
  completed: '完成', failed: '失败', running: '运行中', cancelled: '已停止', error: '出错', queued: '排队中',
};
const TRIGGER_KINDS = [
  ['cron', '定时（cron）'], ['interval', '固定间隔'], ['date', '某时刻一次'], ['event', '文件变化'], ['webhook', 'Webhook'],
] as const;

interface CreateForm {
  name: string; owner: string; kind: 'cron' | 'interval' | 'date' | 'event' | 'webhook';
  cron: string; everyHours: string; at: string; path: string; glob: string;
  message: string; agent: string; script: string; deliver: 'none' | 'channel'; channel: string; target: string; catchup: boolean;
}
const EMPTY_FORM: CreateForm = {
  name: '', owner: '', kind: 'cron', cron: '0 9 * * *', everyHours: '4', at: '', path: '', glob: '',
  message: '', agent: '', script: '', deliver: 'none', channel: 'telegram', target: '', catchup: false,
};

/** 持续目标仍长在旧调度形状上（/api/goals），这里保留它们的人话渲染。 */
interface LegacyTriggerShape { trigger_type: string; trigger_args?: Record<string, unknown> }
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
const CRON_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const EVENTS: Record<string, string> = { 'run.completed': '有任务完成时', 'run.failed': '有任务失败时', 'file.changed': '文件夹里的文件变了' };
const pad = (value: unknown) => String(value ?? 0).padStart(2, '0');
export function describeSchedule(task: LegacyTriggerShape): string {
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
  if (task.trigger_type === 'event') return EVENTS[String(args.event)] ?? String(args.event ?? '事件');
  return task.trigger_type;
}

/**
 * 自动化：产品状态在 /api/automations（W4）。旧 /api/schedules 的一次性导入入口保留。
 * payload.kind=heartbeat 的条目是心跳的投影，只读（编辑心跳请去 Agent 的 Heartbeat 页）。
 */
export default function AutomationPage({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const automations = useAtlasStore((state) => state.automations);
  const engineStarted = useAtlasStore((state) => state.automationsEngineStarted);
  const loading = useAtlasStore((state) => state.automationsLoading);
  const error = useAtlasStore((state) => state.automationsError);
  const loadAutomations = useAtlasStore((state) => state.loadAutomations);
  const createAutomation = useAtlasStore((state) => state.createAutomation);
  const deleteAutomation = useAtlasStore((state) => state.deleteAutomation);
  const runAutomationNow = useAtlasStore((state) => state.runAutomationNow);
  const pauseAutomation = useAtlasStore((state) => state.pauseAutomation);
  const resumeAutomation = useAtlasStore((state) => state.resumeAutomation);
  const loadAutomationRuns = useAtlasStore((state) => state.loadAutomationRuns);
  const importLegacyAutomations = useAtlasStore((state) => state.importLegacyAutomations);
  const migrationReport = useAtlasStore((state) => state.migrationReport);
  const agents = useAtlasStore((state) => state.agents);
  const loadAgents = useAtlasStore((state) => state.loadAgents);
  const runs = useAtlasStore((state) => state.automationRuns);

  const [tab, setTab] = useState<'tasks' | 'goals'>('tasks');
  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);

  const refresh = useCallback(() => { void loadAutomations(); }, [loadAutomations]);
  useEffect(() => { refresh(); void loadAgents(); }, [refresh, loadAgents]);
  useEffect(() => setConfirmDelete(false), [selected]);
  useEffect(() => {
    if (selected || !automations.length) return;
    setSelected(automations[0].id);
  }, [automations, selected]);
  // 引擎没接线时 run-now/runs 都是 503，只刷列表。
  const current = automations.find((item) => item.id === selected);
  useEffect(() => {
    if (!current || !engineStarted) return;
    void loadAutomationRuns(current.id);
  }, [current?.id, current?.last_run_at, engineStarted, loadAutomationRuns]);

  const agentsById = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents]);
  const editable = (item: AutomationRecord) => item.payload?.kind !== 'heartbeat';

  const act = async (task: () => Promise<unknown>, done: string) => {
    setBusy(true);
    await task();
    setBusy(false);
    const failure = useAtlasStore.getState().automationsError;
    onToast(failure || done);
  };

  const create = (event: FormEvent) => {
    event.preventDefault();
    const payload = {
      name: form.name.trim() || form.message.trim().slice(0, 24) || '新自动化',
      owner_agent_id: form.owner,
      trigger: form.kind === 'cron'
        ? { kind: 'cron', cron_expr: form.cron.trim() }
        : form.kind === 'interval'
          ? { kind: 'interval', every_seconds: Math.max(60, (Number(form.everyHours) || 1) * 3600) }
          : form.kind === 'date'
            ? { kind: 'date', at: form.at }
            : form.kind === 'event'
              ? { kind: 'event', event_path: form.path.trim(), ...(form.glob.trim() ? { event_glob: form.glob.trim() } : {}) }
              : { kind: 'webhook' },
      payload: form.script.trim()
        ? { kind: 'script', script: form.script, timeout_seconds: 120 }
        : { kind: 'agent_turn', message: form.message.trim(), agent_id: form.agent || form.owner },
      delivery: form.deliver === 'channel' ? { mode: 'channel', channel: form.channel, target: form.target.trim() } : { mode: 'none' },
      policy: { missed_run: form.catchup ? 'catchup' : 'skip' },
    };
    void act(async () => {
      const record = await createAutomation(payload);
      if (record) { setCreating(false); setSelected(record.id); setForm({ ...EMPTY_FORM }); }
    }, '自动化已创建');
  };

  const doImport = async () => {
    setImporting(true);
    const report = await importLegacyAutomations();
    setImporting(false);
    onToast(report ? `导入完成：${report.imported_count} 条成功，${report.skipped_count} 条跳过` : '导入失败');
  };

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>自动化</h1><p>让 Atlas 按时、或者在某件事发生时替你做事。心跳和定时任务都在这里。</p></div>
      {tab === 'tasks' && <div className="btns">
        <button className="btn ghost" onClick={() => void refresh()} disabled={loading} aria-label="刷新自动化">{loading ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        <button className="btn" disabled={importing || !connected} onClick={() => void doImport()} title="把旧版 /api/schedules 的调度一次性导入">
          {importing ? <LoaderCircle size={15} className="spin" /> : <Upload size={15} />}导入旧调度
        </button>
        <button className="btn primary" disabled={!connected} onClick={() => setCreating(true)}><Plus size={15} />新建自动化</button>
      </div>}
    </header>

    <div role="tablist" aria-label="自动化类型" className="mb-4 flex gap-5 shadow-[inset_0_-1px_0_var(--line)]">
      {([['tasks', '定时与触发'], ['goals', '持续目标']] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
        className={tab === id ? 'pb-2.5 text-[13.5px] font-medium text-fg shadow-[inset_0_-2px_0_var(--brand)]' : 'pb-2.5 text-[13.5px] text-fg-3 hover:text-fg'}>{label}</button>)}
    </div>

    {!connected && <div className="error-note">Atlas 后端未连接。</div>}
    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => void refresh()}><X size={15} /></button></div>}
    {engineStarted === false && <div className="error-note" role="status" style={{ background: 'var(--sunken)', color: 'var(--fg-2)' }}>
      <Power size={15} />自动化引擎（DBOS）还没有接线：列表和编辑可用，「立即运行 / 运行历史」暂不可用。
    </div>}

    {migrationReport && <details className="card glass mb-3.5 px-4 py-3" aria-label="导入报告">
      <summary className="cursor-pointer select-none text-[13px] text-fg-2">
        旧调度导入报告：成功 {migrationReport.imported_count} 条 · 跳过 {migrationReport.skipped_count} 条
      </summary>
      <div className="mt-2 grid gap-1 text-[12.5px] text-fg-3">
        {migrationReport.imported.map((item, index) => <p key={index} className="m-0">已导入：{String(item.name ?? item.id ?? '?')}</p>)}
        {migrationReport.skipped.map((item, index) => <p key={index} className="m-0 text-danger">跳过：{String(item.name ?? item.id ?? '?')}（{String(item.reason ?? '')}）</p>)}
      </div>
    </details>}

    {tab === 'goals' && <GoalsPanel apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} />}
    {tab === 'tasks' && <>
      {creating && <form className="card glass form mb-3.5" onSubmit={create}>
        <h2>新建自动化</h2>
        <div className="two">
          <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="留空则用内容开头" /></label>
          <label>归谁（owner Agent）
            <select value={form.owner} onChange={(event) => setForm({ ...form, owner: event.target.value })}>
              <option value="">系统（Atlas 自己）</option>
              {agents.filter((agent) => agent.kind === 'persistent').map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
        </div>
        <label>什么时候触发
          <select value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as CreateForm['kind'] })}>
            {TRIGGER_KINDS.map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}
          </select>
        </label>
        <div className="two">
          {form.kind === 'cron' && <label>cron 表达式<input required value={form.cron} onChange={(event) => setForm({ ...form, cron: event.target.value })} placeholder="0 9 * * *" /></label>}
          {form.kind === 'interval' && <label>间隔（小时）<input type="number" min={1} step="0.5" value={form.everyHours} onChange={(event) => setForm({ ...form, everyHours: event.target.value })} /></label>}
          {form.kind === 'date' && <label>时刻<input type="datetime-local" required value={form.at} onChange={(event) => setForm({ ...form, at: event.target.value })} /></label>}
          {form.kind === 'event' && <>
            <label>监视的文件夹<input required value={form.path} onChange={(event) => setForm({ ...form, path: event.target.value })} placeholder="D:\项目\docs" /></label>
            <label>只看这些文件（可选）<input value={form.glob} onChange={(event) => setForm({ ...form, glob: event.target.value })} placeholder="*.md" /></label>
          </>}
          {form.kind === 'webhook' && <p className="m-0 self-end text-[12.5px] text-fg-3">保存后会得到一个回调地址，HTTP 打到它就触发一次。</p>}
        </div>
        <label>要做什么
          <textarea required={!form.script.trim()} value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })}
            placeholder="例如：整理今天 GitHub 上我关注仓库的新 issue，挑出需要我回复的" />
        </label>
        <div className="two">
          <label>交给哪个 Agent
            <select value={form.agent} onChange={(event) => setForm({ ...form, agent: event.target.value })}>
              <option value="">默认 Atlas</option>
              {agents.filter((agent) => agent.kind === 'persistent').map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
          <label>或者只跑脚本（填了就不走模型）<input value={form.script} onChange={(event) => setForm({ ...form, script: event.target.value })} placeholder="python scripts/report.py" /></label>
        </div>
        <div className="two">
          <label>结果投递
            <select value={form.deliver} onChange={(event) => setForm({ ...form, deliver: event.target.value as CreateForm['deliver'] })}>
              <option value="none">留在任务里</option>
              <option value="channel">发到渠道</option>
            </select>
          </label>
          {form.deliver === 'channel' && <>
            <label>渠道
              <select value={form.channel} onChange={(event) => setForm({ ...form, channel: event.target.value })}>
                {['telegram', 'slack', 'email', 'webhook'].map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
            <label>目标（chat id 等）<input required value={form.target} onChange={(event) => setForm({ ...form, target: event.target.value })} placeholder="123456789" /></label>
          </>}
        </div>
        <label className="flex items-center gap-2 text-[13px] text-fg-2">
          <input type="checkbox" checked={form.catchup} onChange={(event) => setForm({ ...form, catchup: event.target.checked })} />
          错过的运行要补跑（否则直接跳过）
        </label>
        <div className="foot"><button type="button" className="btn ghost" onClick={() => setCreating(false)}>取消</button><button className="btn primary" disabled={busy}>创建自动化</button></div>
      </form>}

      <div className="split">
        <div className="list glass" role="listbox" aria-label="自动化任务">
          {automations.map((item) => {
            const heartbeat = item.payload?.kind === 'heartbeat';
            const Icon = heartbeat ? HeartPulse : item.trigger.kind === 'event' ? FileCog : item.trigger.kind === 'interval' ? Timer
              : item.trigger.kind === 'cron' ? Repeat : item.trigger.kind === 'webhook' ? Globe : CalendarClock;
            return <button className="row" role="option" key={item.id} aria-selected={item.id === selected} onClick={() => setSelected(item.id)}>
              <span className={heartbeat ? 'ico ether' : 'ico dim'}><Icon size={17} /></span>
              <span style={{ minWidth: 0 }}>
                <p>{item.name}{heartbeat && <span className="ml-1.5 rounded-full bg-brand-soft px-1.5 py-0.5 text-[10.5px] text-fg">心跳</span>}</p>
                <small>{describeTrigger(item.trigger)}，{describeAutomation(item).split('：')[1] ?? ''}</small>
              </span>
              <span className="when">
                <b>{!item.enabled || item.paused_reason ? '已暂停' : item.next_run_at ? relativeTime(item.next_run_at) : item.trigger.kind === 'event' || item.trigger.kind === 'webhook' ? '等事件' : '—'}</b>
                {Boolean(item.consecutive_errors) ? `连续出错 ${item.consecutive_errors} 次` : ' '}
              </span>
            </button>;
          })}
          {!automations.length && !loading && <div className="empty"><Repeat size={22} /><b>还没有自动化</b>比如「每天 9 点总结邮件」，或在 Agent 的 Heartbeat 页打开心跳。</div>}
        </div>

        {current ? <aside className="detail glass" aria-label="自动化详情">
          <h2>{current.name}</h2>
          <div className="sub">
            {!current.enabled || current.paused_reason ? `已暂停${current.paused_reason ? ` · ${current.paused_reason}` : ''}` : '启用中'} · {describeTrigger(current.trigger)}
          </div>
          <dl>
            <div><dt>做什么</dt><dd>{describeAutomation(current)}</dd></div>
            <div><dt>归属</dt><dd>{current.owner_agent_id ? agentsById.get(current.owner_agent_id)?.name ?? current.owner_agent_id : '系统'}</dd></div>
            <div><dt>下次运行</dt><dd>{current.enabled && !current.paused_reason && current.next_run_at ? `${new Date(current.next_run_at).toLocaleString()}（${relativeTime(current.next_run_at)}）` : '未排期'}</dd></div>
            <div><dt>上次运行</dt><dd>{current.last_run_at ? `${new Date(current.last_run_at).toLocaleString()}（${relativeTime(current.last_run_at)}）` : '还没运行过'}</dd></div>
            {Boolean(current.consecutive_errors) && <div><dt>连续出错</dt><dd>{current.consecutive_errors} 次（到阈值会自动停用）</dd></div>}
          </dl>

          {editable(current) ? <>
            <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>最近运行</h3>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4, fontSize: 12.5 }}>
              {(runs[current.id] ?? []).slice(0, 8).map((run, index) => <li key={run.workflow_run_id ?? index} style={{ display: 'flex', gap: 8 }}>
                <span style={{ color: run.status === 'failed' || run.status === 'error' ? 'var(--danger)' : 'var(--ink2)' }}>{RUN_STATUS[run.status ?? ''] ?? run.status ?? '—'}</span>
                <span style={{ color: 'var(--ink3)' }}>{relativeTime(run.started_at)}</span>
              </li>)}
              {!(runs[current.id] ?? []).length && <li style={{ color: 'var(--ink3)' }}>{engineStarted ? '还没有运行记录' : '引擎未接线，暂无运行记录'}</li>}
            </ul>
            <div className="btns">
              <button className="btn primary" disabled={busy || !engineStarted} onClick={() => void act(() => runAutomationNow(current.id), '已开始运行')}><Play size={14} />立即运行</button>
              <button className="btn ghost" disabled={busy} onClick={() => void act(() => current.enabled && !current.paused_reason ? pauseAutomation(current.id) : resumeAutomation(current.id), current.enabled && !current.paused_reason ? '已暂停' : '已恢复')}>
                {current.enabled && !current.paused_reason ? <Pause size={14} /> : <Play size={14} />}{current.enabled && !current.paused_reason ? '暂停' : '恢复'}
              </button>
              <button className={`btn ${confirmDelete ? 'danger' : 'ghost'}`} disabled={busy}
                onClick={() => { if (!confirmDelete) { setConfirmDelete(true); return; } void act(async () => { await deleteAutomation(current.id); setSelected(''); }, '已删除自动化'); }}>
                <Trash2 size={14} />{confirmDelete ? '确认删除' : '删除'}
              </button>
            </div>
          </> : <p className="mb-0 mt-4 rounded-xl bg-sunken px-3.5 py-2.5 text-[12.5px] leading-[1.6] text-fg-3">
            这是心跳条目（payload.kind=heartbeat）：由 <b className="text-fg-2">{agentsById.get(current.payload?.agent_id ?? '')?.name ?? current.payload?.agent_id ?? 'Agent'}</b> 的心跳配置生成，这里只读。要改间隔或活跃时间，去 Agents → 它 → Heartbeat。
          </p>}
        </aside> : <div />}
      </div>
    </>}
  </div></div>;
}
