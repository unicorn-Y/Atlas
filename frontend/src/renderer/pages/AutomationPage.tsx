import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarClock, Copy, FileCog, Globe, HeartPulse, LoaderCircle, Pause, Play, Plus, Power,
  RefreshCw, Repeat, Timer, Trash2, Upload, X,
} from 'lucide-react';
import { useAtlasStore } from '../store/useAtlasStore';
import { relativeTime } from '../services/api';
import type { AutomationRecord } from '../services/persistentApi';
import { automationsApi } from '../services/persistentApi';
import GoalsPanel from './GoalsPanel';
import { describeAutomation, describeTrigger } from './automations/describe';
import { AUTOMATION_TEMPLATES, AUTOMATION_TEMPLATE_CATALOG_VERSION, materializeAutomationTemplate } from './automations/templateCatalog';

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
  executionMode: 'local' | 'worktree'; baseDirectory: string; cleanupPolicy: 'keep' | 'remove_after_run';
}
const EMPTY_FORM: CreateForm = {
  name: '', owner: '', kind: 'cron', cron: '0 9 * * *', everyHours: '4', at: '', path: '', glob: '',
  message: '', agent: '', script: '', deliver: 'none', channel: 'telegram', target: '', catchup: false,
  executionMode: 'local', baseDirectory: '', cleanupPolicy: 'keep',
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
  const [templateChoiceOpen, setTemplateChoiceOpen] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [templateParameters, setTemplateParameters] = useState<Record<string, string>>({});
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editingId, setEditingId] = useState('');
  const [webhookCredential, setWebhookCredential] = useState<{ id: string; secret: string; url: string } | null>(null);
  const [emergency, setEmergency] = useState<{ paused: boolean; affected?: Array<{ id: string; name?: string; cancelled?: number; error?: string }> }>({ paused: false });
  const [emergencyBusy, setEmergencyBusy] = useState(false);

  const refresh = useCallback(() => { void loadAutomations(); }, [loadAutomations]);
  useEffect(() => { refresh(); void loadAgents(); void automationsApi.emergencyStatus(apiBaseUrl).then(setEmergency).catch(() => undefined); }, [refresh, loadAgents, apiBaseUrl]);
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
  const selectedTemplate = AUTOMATION_TEMPLATES.find((item) => item.id === selectedTemplateId);
  const chooseTemplate = (templateId: string) => {
    const template = AUTOMATION_TEMPLATES.find((item) => item.id === templateId);
    const parameters = Object.fromEntries((template?.parameters ?? []).map((item) => [item.key, item.defaultValue]));
    setSelectedTemplateId(template?.id ?? '');
    setTemplateParameters(parameters);
    setForm(template ? {
      ...EMPTY_FORM, name: template.name, kind: template.trigger.kind,
      cron: template.trigger.cron ?? EMPTY_FORM.cron,
      everyHours: template.trigger.everyHours ?? EMPTY_FORM.everyHours,
      path: template.trigger.path ?? '', glob: template.trigger.glob ?? '',
      message: materializeAutomationTemplate(template, parameters),
    } : { ...EMPTY_FORM });
    setTemplateChoiceOpen(false);
  };
  const updateTemplateParameter = (key: string, value: string) => {
    const next = { ...templateParameters, [key]: value };
    setTemplateParameters(next);
    if (selectedTemplate) setForm((current) => ({
      ...current,
      message: materializeAutomationTemplate(selectedTemplate, next),
      ...(selectedTemplate.trigger.kind === 'event' && key === 'folder' ? { path: value } : {}),
    }));
  };

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
        : { kind: 'agent_turn', message: form.message.trim(), agent_id: form.agent || form.owner,
          execution_mode: form.executionMode, base_directory: form.baseDirectory.trim(), cleanup_policy: form.cleanupPolicy },
      delivery: form.deliver === 'channel' ? { mode: 'channel', channel: form.channel, target: form.target.trim() } : { mode: 'none' },
      policy: { missed_run: form.catchup ? 'catchup' : 'skip' },
    };
    void act(async () => {
      if (editingId) {
        const updated = await useAtlasStore.getState().patchAutomation(editingId, payload);
        if (!updated) throw new Error(useAtlasStore.getState().automationsError || '保存自动化失败');
        await loadAutomations(); setCreating(false); setEditingId(''); setForm({ ...EMPTY_FORM });
      } else {
        const record = await createAutomation(payload);
        if (record) { setCreating(false); setSelected(record.id); setForm({ ...EMPTY_FORM }); }
      }
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
        <button className={emergency.paused ? 'btn primary' : 'btn danger'} disabled={!connected || emergencyBusy} aria-label={emergency.paused ? '恢复全局自动化' : '紧急暂停：停止所有自动化和正在运行的任务'} title="紧急暂停：停止所有自动化、正在运行的对话任务、子 Agent、后台进程和浏览器会话；恢复只重新启用暂停前启用的自动化"
          onClick={() => { setEmergencyBusy(true); void (emergency.paused ? automationsApi.emergencyResume(apiBaseUrl) : automationsApi.emergencyPause(apiBaseUrl)).then((result) => {
            setEmergency({ paused: result.paused, affected: 'affected' in result ? result.affected : emergency.affected });
            const activity = (result as { activity?: { stopped: Array<{ id: string; name?: string }>; failed: Array<{ id: string; name?: string; reason?: string }> } }).activity;
            onToast(result.paused ? `全局暂停完成：${result.affected?.length ?? 0} 项自动化已处理；停止 ${activity?.stopped.length ?? 0} 项正在运行的任务（对话/子 Agent/后台进程/浏览器）${activity?.failed.length ? `，${activity.failed.length} 项停止失败：${activity.failed.map((item) => `${item.name ?? item.id}（${item.reason ?? '未知原因'}）`).join('；')}` : ''}` : `已恢复 ${result.resumed?.length ?? 0} 项此前启用的自动化${result.failures?.length ? `；${result.failures.length} 项失败` : ''}`);
            refresh();
          }).catch((error) => onToast(`全局控制失败：${error instanceof Error ? error.message : String(error)}`)).finally(() => setEmergencyBusy(false)); }}>
          {emergencyBusy ? <LoaderCircle size={15} className="spin" /> : emergency.paused ? <Play size={15} /> : <Pause size={15} />}{emergency.paused ? '恢复全部' : '紧急暂停全部'}
        </button>
        <button className="btn ghost" onClick={() => void refresh()} disabled={loading} aria-label="刷新自动化">{loading ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        <button className="btn" disabled={importing || !connected} onClick={() => void doImport()} title="把旧版 /api/schedules 的调度一次性导入">
          {importing ? <LoaderCircle size={15} className="spin" /> : <Upload size={15} />}导入旧调度
        </button>
        <button className="btn primary" disabled={!connected} onClick={() => { setEditingId(''); setSelectedTemplateId(''); setTemplateParameters({}); setTemplateChoiceOpen(true); setCreating(true); }}><Plus size={15} />新建自动化</button>
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
    {emergency.paused && <div className="error-note" role="status"><strong>全局紧急暂停中。</strong> 新触发已阻止；恢复只会重新启用暂停前已启用的任务。{emergency.affected?.map((item) => <span key={item.id} className="block">{item.name ?? item.id}：{item.error ? `失败：${item.error}` : `已停止 ${item.cancelled ?? 0} 个运行`}</span>)}</div>}

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
      {creating && !editingId && templateChoiceOpen && <section className="card glass mb-3.5 p-4" aria-label="选择自动化模板">
        <div className="flex items-start gap-2"><div className="min-w-0 flex-1"><h2 className="m-0 text-[15px] font-semibold text-fg">先选择一个任务模板</h2><p className="mb-3 mt-1 text-[11.5px] text-fg-3">内置模板目录 v{AUTOMATION_TEMPLATE_CATALOG_VERSION} · 选择后可修改触发器、参数和任务内容；创建结果仍保存为普通自动化。</p></div><button type="button" className="btn ghost" onClick={() => { setCreating(false); setTemplateChoiceOpen(false); }}>取消</button></div>
        <div className="grid gap-2 sm:grid-cols-2">{AUTOMATION_TEMPLATES.map((template) => <button key={template.id} type="button" className="rounded-xl border border-line bg-panel p-3 text-left hover:border-brand" onClick={() => chooseTemplate(template.id)}><b className="block text-[13px] text-fg">{template.name}<span className="ml-1 text-[10px] text-fg-3">v{template.version}</span></b><span className="mt-1 block text-[11.5px] leading-5 text-fg-3">{template.purpose}</span><span className="mt-2 block text-[10.5px] text-brand">{template.trigger.kind === 'cron' ? `定时 · ${template.trigger.cron}` : template.trigger.kind === 'event' ? '文件变化触发' : '固定间隔'}</span></button>)}
          <button type="button" className="rounded-xl border border-line bg-panel p-3 text-left hover:border-brand" onClick={() => chooseTemplate('')}><b className="block text-[13px] text-fg">从空白开始</b><span className="mt-1 block text-[11.5px] leading-5 text-fg-3">不套用模板，手动配置触发条件和任务描述。</span></button>
        </div>
      </section>}
      {creating && (!templateChoiceOpen || Boolean(editingId)) && <form className="card glass form mb-3.5" onSubmit={create}>
        <h2>{editingId ? '编辑自动化' : '新建自动化'}</h2>
        {!editingId && <div className="flex items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-[11px] text-fg-3"><span className="flex-1">{selectedTemplate ? `模板：${selectedTemplate.name} v${selectedTemplate.version}（目录 v${AUTOMATION_TEMPLATE_CATALOG_VERSION}）` : '空白自动化'}</span><button type="button" className="text-brand hover:underline" onClick={() => setTemplateChoiceOpen(true)}>更换模板</button></div>}
        {selectedTemplate && !editingId && <section className="rounded-lg border border-line bg-sunken p-3" aria-label="模板参数和任务预览">
          <b className="text-[12px] text-fg">模板参数</b>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">{selectedTemplate.parameters.map((parameter) => <label key={parameter.key} className="grid gap-1 text-[11.5px] text-fg-2">{parameter.label}<input value={templateParameters[parameter.key] ?? ''} onChange={(event) => updateTemplateParameter(parameter.key, event.target.value)} placeholder={parameter.placeholder} className="rounded-lg border border-line bg-panel px-2.5 py-2 text-[12px] text-fg" /></label>)}</div>
          <div className="mt-3 border-t border-line pt-2"><b className="text-[11px] text-fg-3">生成的任务内容预览</b><pre className="mb-0 mt-1 whitespace-pre-wrap break-words text-[12px] leading-5 text-fg-2">{materializeAutomationTemplate(selectedTemplate, templateParameters)}</pre></div>
        </section>}
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
        {!form.script.trim() && <>
          <div className="two">
            <label>执行位置
              <select value={form.executionMode} onChange={(event) => setForm({ ...form, executionMode: event.target.value as CreateForm['executionMode'] })}>
                <option value="local">本地工作区</option><option value="worktree">为每次运行新建隔离 worktree</option>
              </select>
            </label>
            {form.executionMode === 'worktree' && <label>完成后处理
              <select value={form.cleanupPolicy} onChange={(event) => setForm({ ...form, cleanupPolicy: event.target.value as CreateForm['cleanupPolicy'] })}>
                <option value="keep">保留 worktree 供检查</option><option value="remove_after_run">运行完成后删除 worktree 和分支</option>
              </select>
            </label>}
          </div>
          <label>基准目录{form.executionMode === 'worktree' ? '（Git 仓库必填）' : '（可选，留空使用 Atlas 默认）'}
            <input required={form.executionMode === 'worktree'} value={form.baseDirectory} onChange={(event) => setForm({ ...form, baseDirectory: event.target.value })} placeholder="C:\\Projects\\my-app" />
          </label>
          {form.executionMode === 'worktree' && <p className="m-0 text-[12px] text-fg-3">每次触发会从所选仓库当前分支创建独立分支和目录；运行记录包含工作树路径、分支和结果。</p>}
        </>}
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
        <div className="foot"><button type="button" className="btn ghost" onClick={() => { setCreating(false); setEditingId(''); }}>取消</button><button className="btn primary" disabled={busy}>{editingId ? '保存更改' : '创建自动化'}</button></div>
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
            {current.payload.execution_mode === 'worktree' && current.payload.worktree_path && <div><dt>最近工作树</dt><dd className="break-all">{current.payload.worktree_branch} · {current.payload.worktree_path}</dd></div>}
            {Boolean(current.consecutive_errors) && <div><dt>连续出错</dt><dd>{current.consecutive_errors} 次（到阈值会自动停用）</dd></div>}
          </dl>

          {current.trigger.kind === 'webhook' && <section className="mt-3 rounded-xl bg-sunken p-3" aria-label="Webhook 入站路由">
            <h3 className="m-0 text-[13px] font-semibold">外部 Webhook 入站</h3>
            <p className="my-1 text-[12px] text-fg-3">POST JSON 并设置 <code>X-Atlas-Timestamp</code>（Unix 秒）与 <code>X-Atlas-Signature: sha256=&lt;HMAC-SHA256(secret, timestamp + "." + 原始请求体)&gt;</code>。请求最多 256 KiB，时间戳需在 5 分钟内；签名仅可用一次。密钥仅在生成时显示，请安全保存。</p>
            <code className="block break-all text-[11px] text-fg-2">{apiBaseUrl.replace(/\/$/, '')}/api/automations/{encodeURIComponent(current.id)}/webhook</code>
            <button className="btn ghost mt-2" onClick={() => { void navigator.clipboard?.writeText(`${apiBaseUrl.replace(/\/$/, '')}/api/automations/${encodeURIComponent(current.id)}/webhook`).then(() => onToast('Webhook 地址已复制')); }}><Copy size={13} />复制地址</button>
            {webhookCredential?.id === current.id && <div className="mt-2">
              <label className="block text-[11px] text-fg-3">新密钥（本次可见）<input readOnly value={webhookCredential.secret} className="mt-1 w-full select-all font-mono" onFocus={(event) => event.currentTarget.select()} /></label>
              <p className="mb-0 mt-1 break-all text-[11px] text-fg-3">复制请求地址：{webhookCredential.url}</p>
            </div>}
            <button className="btn ghost mt-2" disabled={busy || !connected} onClick={() => void act(async () => {
              const result = await automationsApi.rotateWebhookSecret(apiBaseUrl, current.id);
              setWebhookCredential({ id: current.id, secret: result.secret, url: `${apiBaseUrl.replace(/\/$/, '')}${result.url}` });
              await navigator.clipboard?.writeText(result.secret);
            }, 'Webhook 密钥已轮换并复制到剪贴板')}><RefreshCw size={13} />{webhookCredential?.id === current.id ? '重新轮换密钥' : '生成 / 轮换密钥'}</button>
          </section>}

          {editable(current) ? <>
            <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>最近运行</h3>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4, fontSize: 12.5 }}>
              {(runs[current.id] ?? []).slice(0, 8).map((run, index) => <li key={run.workflow_run_id ?? index} style={{ display: 'flex', gap: 8 }}>
                <span style={{ color: run.status === 'failed' || run.status === 'error' ? 'var(--danger)' : 'var(--ink2)' }}>{RUN_STATUS[run.status ?? ''] ?? run.status ?? '—'}</span>
                <span style={{ color: 'var(--ink3)' }}>{relativeTime(run.started_at ?? (typeof run.created_at === 'string' ? run.created_at : undefined))}</span>
                {typeof run.result === 'object' && run.result && <details style={{ minWidth: 0, color: 'var(--ink3)' }}>
                  <summary className="cursor-pointer">运行详情{typeof (run.result as Record<string, unknown>).worktree_path === 'string' ? ` · worktree ${String((run.result as Record<string, unknown>).worktree_branch ?? '')}` : ''}</summary>
                  {typeof (run.result as Record<string, unknown>).worktree_path === 'string' && <p className="m-0 break-all">路径：{String((run.result as Record<string, unknown>).worktree_path)}</p>}
                  {typeof (run.result as Record<string, unknown>).text === 'string' && <pre className="m-0 max-h-32 overflow-auto whitespace-pre-wrap">{String((run.result as Record<string, unknown>).text)}</pre>}
                  {typeof (run.result as Record<string, unknown>).stdout === 'string' && <pre className="m-0 max-h-32 overflow-auto whitespace-pre-wrap">{String((run.result as Record<string, unknown>).stdout)}</pre>}
                </details>}
                {typeof run.error === 'string' && run.error && <details style={{ minWidth: 0, color: 'var(--danger)' }}><summary className="cursor-pointer">错误详情</summary><p className="m-0 whitespace-pre-wrap">{run.error}</p></details>}
              </li>)}
              {!(runs[current.id] ?? []).length && <li style={{ color: 'var(--ink3)' }}>{engineStarted ? '还没有运行记录' : '引擎未接线，暂无运行记录'}</li>}
            </ul>
            <div className="btns">
              <button className="btn primary" disabled={busy || !engineStarted} onClick={() => void act(() => runAutomationNow(current.id), '已开始运行')}><Play size={14} />立即运行</button>
              <button className="btn ghost" disabled={busy} onClick={() => void act(() => current.enabled && !current.paused_reason ? pauseAutomation(current.id) : resumeAutomation(current.id), current.enabled && !current.paused_reason ? '已暂停' : '已恢复')}>
                {current.enabled && !current.paused_reason ? <Pause size={14} /> : <Play size={14} />}{current.enabled && !current.paused_reason ? '暂停' : '恢复'}
              </button>
              <button className="btn ghost" disabled={busy} onClick={() => {
                const payload = current.payload ?? {};
                setForm({ ...EMPTY_FORM, name: current.name, owner: current.owner_agent_id ?? '', kind: current.trigger.kind,
                  cron: current.trigger.cron_expr ?? EMPTY_FORM.cron, everyHours: String((current.trigger.every_seconds ?? 3600) / 3600),
                  at: current.trigger.at ?? '', path: current.trigger.event_path ?? '', glob: current.trigger.event_glob ?? '',
                  message: payload.message ?? '', agent: payload.agent_id ?? '', script: payload.script ?? '',
                  executionMode: payload.execution_mode ?? 'local', baseDirectory: payload.base_directory ?? '',
                  cleanupPolicy: payload.cleanup_policy ?? 'keep' });
                setEditingId(current.id); setCreating(true);
              }}>编辑</button>
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
