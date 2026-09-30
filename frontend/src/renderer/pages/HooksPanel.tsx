import { useEffect, useState, type FormEvent } from 'react';
import { FlaskConical, Plus, Trash2, Webhook } from 'lucide-react';
import type { HookConfig } from '@atlas/backend-adapter';
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
const blank = (): HookConfig => ({ id: '', event: 'run.completed', command: '', timeout_s: 30, enabled: true });

/** Your own commands at points in a run; they get the event as JSON on stdin. */
export default function HooksPanel() {
  const [hooks, setHooks] = useState<HookConfig[]>([]);
  const [draft, setDraft] = useState<HookConfig | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const load = () => backend.getHooks().then(setHooks).catch((exc) => setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }));
  useEffect(() => { void load(); }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    try { await backend.saveHook({ ...draft, id: draft.id.trim() }, isNew); setMessage({ ok: true, text: '已保存' }); setIsNew(false); await load(); }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };
  const test = async () => {
    if (!draft || isNew) return;
    try {
      const result = await backend.testHook(draft.id);
      setMessage({ ok: result.exit_code === 0, text: `退出码 ${result.exit_code ?? '?'}，用时 ${result.duration_ms ?? '?'} ms${result.output ? `\n${result.output}` : ''}` });
    } catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };
  const remove = async () => {
    if (!draft) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try { await backend.deleteHook(draft.id); setDraft(null); setConfirmDelete(false); await load(); }
    catch (exc) { setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) }); }
  };

  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-5">
    <nav className="grid content-start gap-1" aria-label="Hook 列表">
      {hooks.map((hook) => <button key={hook.id} onClick={() => { setDraft(hook); setIsNew(false); setMessage(null); setConfirmDelete(false); }} aria-current={draft?.id === hook.id && !isNew}
        className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', draft?.id === hook.id && !isNew ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
        <Webhook size={14} className={cn('shrink-0', hook.enabled ? 'text-brand' : 'text-fg-3')} /><span className="min-w-0 truncate">{hook.id}</span>
      </button>)}
      <button onClick={() => { setDraft(blank()); setIsNew(true); setMessage(null); }} className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', isNew ? 'bg-selected text-fg' : 'text-brand hover:bg-hover')}><Plus size={14} />新建 Hook</button>
    </nav>
    {draft ? <form onSubmit={(event) => void save(event)} className="grid content-start gap-3.5 text-[13px] text-fg-2">
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
        {!isNew && <Button onClick={() => void test()}><FlaskConical />用示例试跑</Button>}
        {!isNew && <Button variant={confirmDelete ? 'danger' : 'ghost'} onClick={() => void remove()}><Trash2 />{confirmDelete ? '确认删除' : '删除'}</Button>}
      </div>
      {message && <pre role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px] whitespace-pre-wrap', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</pre>}
    </form> : <p className="text-[13px] leading-[1.7] text-fg-3">Hook 是在任务的某个节点运行的你自己的命令，比如任务完成时发条通知，或者在 Atlas 改文件前做检查。{hooks.length ? '' : '现在还没有。'}</p>}
  </div>;
}
