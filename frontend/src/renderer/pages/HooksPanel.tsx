import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { FlaskConical, Plus, RefreshCw, Search, Trash2, Webhook } from 'lucide-react';
import type { HookConfig, HookLog } from '@atlas/backend-adapter';
import { api } from '../services/api';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

const EVENTS: Record<string, string> = {
  'run.started': '任务开始时',
  'tool.before': '每次用工具之前（退出码 2 可以拦下）',
  'tool.after': '每次用完工具之后',
  'run.completed': '任务完成时',
  'run.failed': '任务失败时',
};
/** Claude Code 事件的中文说明；Atlas 自己的事件走上面的表。 */
const CLAUDE_EVENTS: Record<string, string> = {
  PreToolUse: '用工具之前（可以拦下或改参数）',
  PostToolUse: '用完工具之后',
  UserPromptSubmit: '你发消息时',
  SessionStart: '会话开始时',
  SessionEnd: '会话结束时',
  Stop: '一轮回答结束时',
  SubagentStop: '子任务结束时',
  Notification: 'Atlas 发通知时',
  PreCompact: '压缩上下文之前',
};
const eventLabel = (event: string) => EVENTS[event] ?? CLAUDE_EVENTS[event] ?? event;
/** 来源标记：Claude 设置里的写明是哪份配置，插件带的也标出来。 */
const sourceLabel = (source: string | undefined) => {
  if (!source || source === 'atlas') return 'Atlas';
  if (source.startsWith('claude:user')) return 'Claude 用户设置';
  if (source.startsWith('claude:project')) return 'Claude 项目设置';
  if (source.startsWith('claude:local')) return 'Claude 项目本地';
  if (source.startsWith('plugin')) return '插件';
  return source;
};
const isAtlasHook = (hook: HookConfig) => !hook.source || hook.source === 'atlas';
type ReviewedHook = HookConfig & {
  handler?: { type: 'command' | 'http' | 'mcp'; command?: string; url?: string; method?: string; headers?: Record<string, string>; server?: string; tool?: string; arguments?: Record<string, unknown> };
  trusted?: boolean;
  trust_state?: 'approved' | 'unreviewed' | 'revoked' | 'changed';
  trust_fingerprint?: string;
  reviewed_at?: string | null;
  policy_source?: string;
  trust_scope?: string;
};
const trustLabel = (hook: ReviewedHook) => hook.trusted
  ? '已批准'
  : hook.trust_state === 'revoked' ? '已撤销'
    : hook.trust_state === 'changed' ? '配置已变化，需重审' : '待审查';
const blank = (): ReviewedHook => ({ id: '', event: 'run.completed', command: '', handler: { type: 'command', command: '' }, timeout_s: 30, enabled: false, trusted: false, trust_state: 'unreviewed' });

/** Your own commands at points in a run; they get the event as JSON on stdin. Claude Code settings and plugin hooks show up here too. */
export default function HooksPanel() {
  const workspace = useAtlasStore((state) => state.conversations.find((item) => item.id === state.activeConversationId)?.workspace);
  const [hooks, setHooks] = useState<ReviewedHook[]>([]);
  const [logs, setLogs] = useState<HookLog[]>([]);
  const [draft, setDraft] = useState<ReviewedHook | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [hookQuery, setHookQuery] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [failedLogsOnly, setFailedLogsOnly] = useState(false);
  const importFile = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await backend.getHooks(workspace ?? undefined);
      const nextHooks = data.hooks as ReviewedHook[];
      setHooks(nextHooks);
      setDraft((current) => current
        ? nextHooks.find((hook) => hook.id === current.id && hook.source === current.source)
          ?? nextHooks.find((hook) => hook.id === current.id)
          ?? current
        : current);
      setLogs(data.logs);
    } catch (exc) {
      setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) });
    } finally { setRefreshing(false); }
  }, [workspace]);
  useEffect(() => { void load(); }, [load]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    try {
      const handler = draft.handler?.type === 'command'
        ? { type: 'command', command: draft.handler.command ?? draft.command }
        : draft.handler;
      await api(backend.apiBaseUrl, isNew ? '/api/hooks/definitions' : `/api/hooks/${encodeURIComponent(draft.id)}/definition`, {
        method: isNew ? 'POST' : 'PUT',
        json: { id: draft.id.trim(), event: draft.event, handler, timeout_s: draft.timeout_s, enabled: draft.enabled },
      });
      setMessage({ ok: true, text: '已保存；保存后的配置变化会要求重新批准' });
      setIsNew(false);
      await load();
    }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };
  const exportHooks = async () => {
    try {
      const data = await api<{ format: string; hooks: unknown[] }>(backend.apiBaseUrl, '/api/hooks/export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = 'atlas-hooks.json'; link.click(); URL.revokeObjectURL(url);
    } catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };
  const importHooks = async (file?: File) => {
    if (!file) return;
    try {
      const result = await api<{ imported: number }>(backend.apiBaseUrl, '/api/hooks/import', { method: 'POST', json: JSON.parse(await file.text()) });
      setMessage({ ok: true, text: `已导入 ${result.imported} 条 Hook；全部保持关闭并等待逐条批准。` });
      await load();
    } catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
    finally { if (importFile.current) importFile.current.value = ''; }
  };
  const test = async (hook: ReviewedHook) => {
    setBusyId(hook.id);
    try {
      const result = await backend.testHook(hook.id, workspace ?? undefined) as HookLog & { blocked?: boolean; reason?: string; review_required?: boolean };
      setMessage({
        ok: result.exit_code === 0,
        text: result.review_required
          ? result.reason ?? 'Hook 尚未批准，已阻止试跑。'
          : `退出码 ${result.exit_code ?? '?'}，用时 ${result.duration_ms ?? '?'} ms${result.output ? `\n${result.output}` : ''}${result.stderr ? `\n${result.stderr}` : ''}`,
      });
      await load();
    } catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
    finally { setBusyId(''); }
  };
  const toggle = async (hook: ReviewedHook) => {
    setBusyId(hook.id);
    try { await backend.setHookEnabled(hook.id, !hook.enabled, workspace ?? undefined); await load(); }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
    finally { setBusyId(''); }
  };
  const review = async (hook: ReviewedHook, trusted: boolean) => {
    if (!hook.trust_fingerprint) {
      setMessage({ ok: false, text: '缺少当前配置指纹，请先刷新 Hook 列表。' });
      return;
    }
    setBusyId(hook.id);
    try {
      await api<ReviewedHook>(backend.apiBaseUrl, `/api/hooks/${encodeURIComponent(hook.id)}/trust`, {
        method: 'PUT',
        json: { trusted, fingerprint: hook.trust_fingerprint, ...(workspace ? { workspace } : {}) },
      });
      setMessage({ ok: true, text: trusted ? '已批准当前配置；Hook 启用状态保持不变。' : '已撤销信任；后续触发会 fail closed。' });
      await load();
    } catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
    finally { setBusyId(''); }
  };
  const remove = async () => {
    if (!draft) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try { await backend.deleteHook(draft.id); setDraft(null); setConfirmDelete(false); await load(); }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };

  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const selectedExternal = draft && !isAtlasHook(draft) ? draft : null;
  const filterEvents = [...new Set([...Object.keys(EVENTS), ...hooks.map((hook) => hook.event)])];
  const visibleHooks = hooks.filter((hook) => {
    const matchesQuery = !hookQuery.trim() || `${hook.id} ${hook.event} ${hook.command} ${hook.matcher ?? ''} ${sourceLabel(hook.source)}`.toLowerCase().includes(hookQuery.trim().toLowerCase());
    const matchesEvent = !eventFilter || hook.event === eventFilter;
    const matchesSource = !sourceFilter || (sourceFilter === 'atlas' ? isAtlasHook(hook) : !isAtlasHook(hook));
    const matchesStatus = !statusFilter || (statusFilter === 'enabled' ? hook.enabled : !hook.enabled);
    return matchesQuery && matchesEvent && matchesSource && matchesStatus;
  });
  const visibleLogs = (failedLogsOnly ? logs.filter((log) => log.exit_code !== 0) : logs).slice().reverse();
  return <div className="grid gap-5">
    <div className="flex flex-wrap items-center gap-2" aria-label="筛选 Hook">
      <label className="flex h-9 min-w-[190px] flex-1 items-center gap-2 rounded-[9px] bg-sunken px-3 text-fg-3 shadow-[inset_0_0_0_1px_var(--line)] focus-within:shadow-[inset_0_0_0_1px_var(--brand)]">
        <Search size={15} />
        <input value={hookQuery} onChange={(event) => setHookQuery(event.target.value)} className="min-w-0 flex-1 bg-transparent text-[13px] text-fg outline-none" placeholder="搜索名称、事件、命令或来源" aria-label="搜索 Hook" />
      </label>
      <select className={field} aria-label="按事件筛选 Hook" value={eventFilter} onChange={(event) => setEventFilter(event.target.value)}>
        <option value="">所有事件</option>
        {filterEvents.map((event) => <option key={event} value={event}>{eventLabel(event)}</option>)}
      </select>
      <select className={field} aria-label="按来源筛选 Hook" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
        <option value="">所有来源</option>
        <option value="atlas">Atlas 自定义</option>
        <option value="external">Claude 设置或插件</option>
      </select>
      <select className={field} aria-label="按启用状态筛选 Hook" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
        <option value="">所有状态</option>
        <option value="enabled">已启用</option>
        <option value="disabled">已停用</option>
      </select>
      <Button onClick={() => void load()} disabled={refreshing} aria-label="刷新 Hook 和运行记录">
        <RefreshCw className={refreshing ? 'animate-spin' : ''} />刷新
      </Button>
      <input ref={importFile} type="file" accept="application/json,.json" className="hidden" aria-label="导入 Atlas Hook JSON" onChange={(event) => void importHooks(event.target.files?.[0])} />
      <Button onClick={() => importFile.current?.click()}>导入 JSON</Button>
      <Button onClick={() => void exportHooks()}>导出 JSON</Button>
    </div>
    <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-5">
      <nav className="grid content-start gap-1" aria-label="Hook 列表">
        {visibleHooks.map((hook) => <button key={hook.id} onClick={() => { setDraft(hook); setIsNew(false); setMessage(null); setConfirmDelete(false); }} aria-current={draft?.id === hook.id && !isNew}
          className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', draft?.id === hook.id && !isNew ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
          <Webhook size={14} className={cn('shrink-0', hook.enabled ? 'text-brand' : 'text-fg-3')} />
          <span className="min-w-0 flex-1 truncate">{hook.id}</span>
          <span className={cn('shrink-0 rounded px-1 py-0.5 text-[10px]', hook.trusted ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger')} title={trustLabel(hook)}>{hook.trusted ? '已批' : '审查'}</span>
          {!isAtlasHook(hook) && <span className="shrink-0 rounded bg-sunken px-1 py-0.5 text-[10px] text-fg-3" title={sourceLabel(hook.source)}>{sourceLabel(hook.source).slice(0, 6)}</span>}
        </button>)}
        {!visibleHooks.length && <p className="m-0 px-2.5 py-2 text-[12px] text-fg-3">没有匹配的 Hook。</p>}
        <button onClick={() => { setDraft(blank()); setIsNew(true); setMessage(null); }} className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', isNew ? 'bg-selected text-fg' : 'text-brand hover:bg-hover')}><Plus size={14} />新建 Hook</button>
      </nav>
      {selectedExternal ? <div className="grid content-start gap-3 text-[13px] text-fg-2">
        <p className="m-0 flex flex-wrap items-center gap-2">
          <span className="rounded bg-sunken px-1.5 py-0.5 text-[11.5px] text-fg-3">来源：{sourceLabel(selectedExternal.source)}</span>
          <span className={cn('rounded px-1.5 py-0.5 text-[11.5px]', selectedExternal.trusted ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger')}>{trustLabel(selectedExternal)}</span>
          <span className="text-fg">{eventLabel(selectedExternal.event)}</span>
          {selectedExternal.matcher ? <span className="text-fg-3">只对匹配「{selectedExternal.matcher}」的工具生效</span> : null}
        </p>
        <pre className="m-0 max-h-40 overflow-auto rounded-lg bg-sunken px-3 py-2 font-mono text-[12px] whitespace-pre-wrap text-fg-2">{selectedExternal.command || '（没有命令内容）'}</pre>
        <p className="m-0 text-[12px] leading-[1.6] text-fg-3">这一条来自 Claude 设置或插件，内容只能在原来的文件里改。未批准或配置变更后的 Hook 不会执行；批准与启用是分开的状态。</p>
        <div className="flex items-center gap-2">
          <Button onClick={() => void review(selectedExternal, !selectedExternal.trusted)} disabled={busyId === selectedExternal.id}>{selectedExternal.trusted ? '撤销信任' : '批准执行'}</Button>
          <Button onClick={() => void toggle(selectedExternal)} disabled={busyId === selectedExternal.id || (!selectedExternal.enabled && !selectedExternal.trusted)}>{selectedExternal.enabled ? '停用' : '启用'}</Button>
          <Button onClick={() => void test(selectedExternal)} disabled={busyId === selectedExternal.id || !selectedExternal.trusted}><FlaskConical />{busyId === selectedExternal.id ? '正在试跑…' : '用示例试跑'}</Button>
        </div>
        {message && <pre role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px] whitespace-pre-wrap', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</pre>}
      </div>
        : draft ? <form onSubmit={(event) => void save(event)} className="grid content-start gap-3.5 text-[13px] text-fg-2">
          {!isNew && <div className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken px-3 py-2">
            <span className={cn('text-[12px]', draft.trusted ? 'text-ok' : 'text-danger')}>信任状态：{trustLabel(draft)}</span>
            <span className="flex-1 text-[11.5px] text-fg-3">来源：{sourceLabel(draft.source)} · 策略：{draft.policy_source ?? 'user review'} · 范围：{draft.trust_scope ?? 'user'} · 批准与启用互相独立</span>
            <Button type="button" onClick={() => void review(draft, !draft.trusted)} disabled={busyId === draft.id}>{draft.trusted ? '撤销信任' : '批准执行'}</Button>
          </div>}
          <label className="grid gap-1">名称（英文、数字、短横线）<input required disabled={!isNew} value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value.replace(/[^\w-]/g, '-') })} className={field} placeholder="notify-done" /></label>
          <label className="grid gap-1">什么时候运行<select value={draft.event} onChange={(event) => setDraft({ ...draft, event: event.target.value })} className={field}>
            {Object.entries(EVENTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="grid gap-1">处理方式<select value={draft.handler?.type ?? 'command'} onChange={(event) => { const type = event.target.value as 'command' | 'http' | 'mcp'; setDraft({ ...draft, command: '', handler: { type } }); }} className={field}><option value="command">本地命令</option><option value="http">HTTP webhook</option><option value="mcp">已连接的 MCP 工具</option></select></label>
          {(draft.handler?.type ?? 'command') === 'command' && <label className="grid gap-1">命令<textarea required value={draft.handler?.command ?? draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value, handler: { type: 'command', command: event.target.value } })} rows={3} className={cn(field, 'h-auto py-2 font-mono text-[12.5px]')} placeholder="python notify.py" /></label>}
          {draft.handler?.type === 'http' && <><label className="grid gap-1">HTTP(S) URL<input required type="url" value={draft.handler.url ?? ''} onChange={(event) => setDraft({ ...draft, handler: { ...draft.handler!, url: event.target.value } })} className={field} /></label><label className="grid gap-1">方法<select value={draft.handler.method ?? 'POST'} onChange={(event) => setDraft({ ...draft, handler: { ...draft.handler!, method: event.target.value } })} className={field}><option>POST</option><option>PUT</option><option>PATCH</option></select></label><label className="grid gap-1">Headers（JSON 对象）<textarea value={JSON.stringify(draft.handler.headers ?? {}, null, 2)} onChange={(event) => { try { const headers = JSON.parse(event.target.value); if (headers && typeof headers === 'object' && !Array.isArray(headers)) setDraft({ ...draft, handler: { ...draft.handler!, headers } }); } catch { /* incomplete JSON stays in the editor until it parses */ } }} rows={3} className={cn(field, 'h-auto py-2 font-mono text-[12.5px]')} /></label></>}
          {draft.handler?.type === 'mcp' && <><label className="grid gap-1">已连接的 MCP server<input required value={draft.handler.server ?? ''} onChange={(event) => setDraft({ ...draft, handler: { ...draft.handler!, server: event.target.value } })} className={field} /></label><label className="grid gap-1">工具名<input required value={draft.handler.tool ?? ''} onChange={(event) => setDraft({ ...draft, handler: { ...draft.handler!, tool: event.target.value } })} className={field} /></label><label className="grid gap-1">Arguments（可选 JSON；留空则传入事件数据）<textarea value={draft.handler.arguments ? JSON.stringify(draft.handler.arguments, null, 2) : ''} onChange={(event) => { try { const args = JSON.parse(event.target.value); if (args && typeof args === 'object' && !Array.isArray(args)) setDraft({ ...draft, handler: { ...draft.handler!, arguments: args } }); } catch { /* incomplete JSON stays in the editor until it parses */ } }} rows={3} className={cn(field, 'h-auto py-2 font-mono text-[12.5px]')} /></label></>}
          <p className="m-0 text-[12px] leading-[1.6] text-fg-3">Hook 默认关闭，且每个工作区需要单独审查。HTTP 收到事件 JSON；MCP 在 Atlas 已连接的 server 上调用指定工具。试跑也会产生真实副作用。</p>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2">超时（秒）<input type="number" min={1} max={300} value={draft.timeout_s} onChange={(event) => setDraft({ ...draft, timeout_s: Number(event.target.value) || 30 })} className={cn(field, 'w-20')} /></label>
            <label className="flex items-center gap-2"><input type="checkbox" disabled={!isNew && !draft.trusted && !draft.enabled} checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />启用</label>
          </div>
          <div className="flex items-center gap-2">
            <Button type="submit" variant="primary" disabled={!draft.id.trim() || (draft.handler?.type === 'command' && !(draft.handler.command ?? draft.command).trim()) || (draft.handler?.type === 'http' && !draft.handler.url?.trim()) || (draft.handler?.type === 'mcp' && (!draft.handler.server?.trim() || !draft.handler.tool?.trim()))}>{isNew ? '创建' : '保存'}</Button>
            {!isNew && <Button type="button" onClick={() => void test(draft)} disabled={busyId === draft.id || !draft.trusted}><FlaskConical />用示例试跑</Button>}
            {!isNew && <Button variant={confirmDelete ? 'danger' : 'ghost'} onClick={() => void remove()}><Trash2 />{confirmDelete ? '确认删除' : '删除'}</Button>}
          </div>
          {message && <pre role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px] whitespace-pre-wrap', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</pre>}
        </form>
          : <p className="text-[13px] leading-[1.7] text-fg-3">Hook 是在任务的某个节点运行的你自己的命令，比如任务完成时发条通知，或者在 Atlas 改文件前做检查。Claude 设置和插件里的 hook 也会列在这里。{hooks.length ? '选中左边一条查看。' : '现在还没有。'}</p>}
    </div>
    <section aria-label="最近的 Hook 运行记录" className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <h4 className="m-0 text-[13px] font-semibold text-fg-2">最近运行记录</h4>
        <label className="flex items-center gap-2 text-[12px] text-fg-3"><input type="checkbox" checked={failedLogsOnly} onChange={(event) => setFailedLogsOnly(event.target.checked)} />只看失败</label>
      </div>
      {visibleLogs.length ? <ul className="m-0 grid max-h-56 gap-1.5 overflow-auto p-0 text-[12px] text-fg-3" style={{ listStyle: 'none' }}>
        {visibleLogs.map((log, index) => {
          const reviewLog = log as HookLog & { review_required?: boolean; reason?: string };
          return <li key={`${log.hook_id ?? ''}-${index}`} className="rounded-lg bg-sunken px-3 py-1.5">
            <span className={log.exit_code === 0 ? 'text-ok' : 'text-danger'}>{reviewLog.review_required ? '未审查，已阻止' : log.exit_code === 0 ? '成功' : `退出码 ${log.exit_code}`}</span>
            {' '}· {eventLabel(log.event)}{log.hook_id ? ` · ${log.hook_id}` : ''} · {log.duration_ms} ms
            {(reviewLog.reason || log.output || log.stderr) && <span className="mt-1 block truncate font-mono" title={(reviewLog.reason || log.stderr || log.output || '').trim()}>{(reviewLog.reason || log.stderr || log.output || '').trim().slice(0, 200)}</span>}
          </li>;
        })}
      </ul> : <p className="m-0 text-[12.5px] text-fg-3">{logs.length ? '没有符合筛选条件的记录。' : '还没有运行过。点「用示例试跑」，或者等下一次任务触发。'}</p>}
    </section>
  </div>;
}
