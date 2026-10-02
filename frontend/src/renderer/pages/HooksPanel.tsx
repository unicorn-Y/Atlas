import { useEffect, useState, type FormEvent } from 'react';
import { FlaskConical, Plus, Trash2, Webhook } from 'lucide-react';
import type { HookConfig, HookLog } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
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
const blank = (): HookConfig => ({ id: '', event: 'run.completed', command: '', timeout_s: 30, enabled: true });

/** Your own commands at points in a run; they get the event as JSON on stdin. Claude Code settings and plugin hooks show up here too. */
export default function HooksPanel() {
  const [hooks, setHooks] = useState<HookConfig[]>([]);
  const [logs, setLogs] = useState<HookLog[]>([]);
  const [draft, setDraft] = useState<HookConfig | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busyId, setBusyId] = useState('');
  const load = () => backend.getHooks().then((data) => { setHooks(data.hooks); setLogs(data.logs); })
    .catch((exc) => setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }));
  useEffect(() => { void load(); }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    try { await backend.saveHook({ ...draft, id: draft.id.trim() }, isNew); setMessage({ ok: true, text: '已保存' }); setIsNew(false); await load(); }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };
  const test = async (hook: HookConfig) => {
    setBusyId(hook.id);
    try {
      const result = await backend.testHook(hook.id);
      setMessage({ ok: result.exit_code === 0, text: `退出码 ${result.exit_code ?? '?'}，用时 ${result.duration_ms ?? '?'} ms${result.output ? `\n${result.output}` : ''}${result.stderr ? `\n${result.stderr}` : ''}` });
      await load();
    } catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
    finally { setBusyId(''); }
  };
  const toggle = async (hook: HookConfig) => {
    setBusyId(hook.id);
    try { await backend.setHookEnabled(hook.id, !hook.enabled); await load(); }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
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
  return <div className="grid gap-5">
    <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-5">
      <nav className="grid content-start gap-1" aria-label="Hook 列表">
        {hooks.map((hook) => <button key={hook.id} onClick={() => { setDraft(hook); setIsNew(false); setMessage(null); setConfirmDelete(false); }} aria-current={draft?.id === hook.id && !isNew}
          className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', draft?.id === hook.id && !isNew ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
          <Webhook size={14} className={cn('shrink-0', hook.enabled ? 'text-brand' : 'text-fg-3')} />
          <span className="min-w-0 flex-1 truncate">{hook.id}</span>
          {!isAtlasHook(hook) && <span className="shrink-0 rounded bg-sunken px-1 py-0.5 text-[10px] text-fg-3" title={sourceLabel(hook.source)}>{isAtlasHook(hook) ? '' : sourceLabel(hook.source).slice(0, 6)}</span>}
        </button>)}
        <button onClick={() => { setDraft(blank()); setIsNew(true); setMessage(null); }} className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', isNew ? 'bg-selected text-fg' : 'text-brand hover:bg-hover')}><Plus size={14} />新建 Hook</button>
      </nav>
      {selectedExternal ? <div className="grid content-start gap-3 text-[13px] text-fg-2">
        <p className="m-0 flex flex-wrap items-center gap-2">
          <span className="rounded bg-sunken px-1.5 py-0.5 text-[11.5px] text-fg-3">来源：{sourceLabel(selectedExternal.source)}</span>
          <span className="text-fg">{eventLabel(selectedExternal.event)}</span>
          {selectedExternal.matcher ? <span className="text-fg-3">只对匹配「{selectedExternal.matcher}」的工具生效</span> : null}
        </p>
        <pre className="m-0 max-h-40 overflow-auto rounded-lg bg-sunken px-3 py-2 font-mono text-[12px] whitespace-pre-wrap text-fg-2">{selectedExternal.command || '（没有命令内容）'}</pre>
        <p className="m-0 text-[12px] leading-[1.6] text-fg-3">这一条来自 Claude 设置或插件，内容只能在原来的文件里改；这里可以临时停用、重新启用，也可以用示例试跑一次看看输出。</p>
        <div className="flex items-center gap-2">
          <Button onClick={() => void toggle(selectedExternal)} disabled={busyId === selectedExternal.id}>{selectedExternal.enabled ? '停用' : '启用'}</Button>
          <Button onClick={() => void test(selectedExternal)} disabled={busyId === selectedExternal.id}><FlaskConical />{busyId === selectedExternal.id ? '正在试跑…' : '用示例试跑'}</Button>
        </div>
        {message && <pre role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px] whitespace-pre-wrap', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</pre>}
      </div>
        : draft ? <form onSubmit={(event) => void save(event)} className="grid content-start gap-3.5 text-[13px] text-fg-2">
          <label className="grid gap-1">名称（英文、数字、短横线）<input required disabled={!isNew} value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value.replace(/[^\w-]/g, '-') })} className={field} placeholder="notify-done" /></label>
          <label className="grid gap-1">什么时候运行<select value={draft.event} onChange={(event) => setDraft({ ...draft, event: event.target.value })} className={field}>
            {Object.entries(EVENTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="grid gap-1">命令<textarea required value={draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value })} rows={3}
            className={cn(field, 'h-auto py-2 font-mono text-[12.5px]')} placeholder={'python D:\\scripts\\notify.py'} /></label>
          <p className="m-0 text-[12px] leading-[1.6] text-fg-3">命令在任务的工作目录里运行，事件内容以 JSON 从标准输入传进去。「用工具之前」的命令退出码为 2 时会拦下这次工具调用，输出会作为理由告诉 Atlas。</p>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2">超时（秒）<input type="number" min={1} max={300} value={draft.timeout_s} onChange={(event) => setDraft({ ...draft, timeout_s: Number(event.target.value) || 30 })} className={cn(field, 'w-20')} /></label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />启用</label>
          </div>
          <div className="flex items-center gap-2">
            <Button type="submit" variant="primary" disabled={!draft.id.trim() || !draft.command.trim()}>{isNew ? '创建' : '保存'}</Button>
            {!isNew && <Button onClick={() => void test(draft)} disabled={busyId === draft.id}><FlaskConical />用示例试跑</Button>}
            {!isNew && <Button variant={confirmDelete ? 'danger' : 'ghost'} onClick={() => void remove()}><Trash2 />{confirmDelete ? '确认删除' : '删除'}</Button>}
          </div>
          {message && <pre role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px] whitespace-pre-wrap', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</pre>}
        </form>
          : <p className="text-[13px] leading-[1.7] text-fg-3">Hook 是在任务的某个节点运行的你自己的命令，比如任务完成时发条通知，或者在 Atlas 改文件前做检查。Claude 设置和插件里的 hook 也会列在这里。{hooks.length ? '选中左边一条查看。' : '现在还没有。'}</p>}
    </div>
    <section aria-label="最近的 Hook 运行记录" className="grid gap-2">
      <h4 className="m-0 text-[13px] font-semibold text-fg-2">最近运行记录</h4>
      {logs.length ? <ul className="m-0 grid max-h-56 gap-1.5 overflow-auto p-0 text-[12px] text-fg-3" style={{ listStyle: 'none' }}>
        {[...logs].reverse().map((log, index) => <li key={`${log.hook_id ?? ''}-${index}`} className="rounded-lg bg-sunken px-3 py-1.5">
          <span className={log.exit_code === 0 ? 'text-ok' : 'text-danger'}>{log.exit_code === 0 ? '成功' : `退出码 ${log.exit_code}`}</span>
          {' '}· {eventLabel(log.event)}{log.hook_id ? ` · ${log.hook_id}` : ''} · {log.duration_ms} ms
          {(log.output || log.stderr) && <span className="mt-1 block truncate font-mono" title={((log.stderr || log.output) ?? '').trim()}>{((log.stderr || log.output) ?? '').trim().slice(0, 200)}</span>}
        </li>)}
      </ul> : <p className="m-0 text-[12.5px] text-fg-3">还没有运行过。点「用示例试跑」，或者等下一次任务触发。</p>}
    </section>
  </div>;
}
