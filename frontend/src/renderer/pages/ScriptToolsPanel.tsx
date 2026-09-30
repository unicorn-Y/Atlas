import { useEffect, useState, type FormEvent } from 'react';
import { FlaskConical, Plus, Trash2, Wrench } from 'lucide-react';
import type { CustomTool } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

type Draft = CustomTool & { commandText: string; schemaText: string; script_name: string; script: string };

const EXAMPLE_SCRIPT = `import json, sys

args = json.load(sys.stdin)          # Atlas 传进来的参数
text = args.get("text", "")
print(json.dumps({"length": len(text), "upper": text.upper()}, ensure_ascii=False))
`;
const EXAMPLE_SCHEMA = JSON.stringify({ type: 'object', properties: { text: { type: 'string', description: '要处理的文字' } }, required: ['text'] }, null, 2);

const blank = (): Draft => ({
  id: '', name: '', description: '', command: [], input_schema: {}, timeout_s: 30, enabled: true,
  commandText: 'python run.py', schemaText: EXAMPLE_SCHEMA, script_name: 'run.py', script: EXAMPLE_SCRIPT,
});
const toDraft = (tool: CustomTool): Draft => ({
  ...tool, commandText: tool.command.join(' '), schemaText: JSON.stringify(tool.input_schema, null, 2), script_name: '', script: '',
});
/** "python run.py --x" → ["python", "run.py", "--x"], keeping "quoted parts" together. */
const splitCommand = (text: string) => [...text.matchAll(/"([^"]*)"|(\S+)/g)].map((match) => match[1] ?? match[2]);

/** Small scripts Atlas can call as tools: arguments arrive as JSON on stdin, stdout is the result. */
export default function ScriptToolsPanel() {
  const [tools, setTools] = useState<CustomTool[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [sample, setSample] = useState('{"text": "hello"}');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const fail = (exc: unknown) => setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) });
  const load = () => backend.getCustomTools().then(setTools).catch(fail);
  useEffect(() => { void load(); }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    let schema: Record<string, unknown>;
    try { schema = JSON.parse(draft.schemaText || '{}'); } catch { setMessage({ ok: false, text: '参数格式不是合法的 JSON。' }); return; }
    const payload = {
      id: draft.id.trim(), name: draft.name.trim(), description: draft.description.trim(), command: splitCommand(draft.commandText),
      input_schema: schema, timeout_s: draft.timeout_s, enabled: draft.enabled,
      ...(draft.script.trim() && draft.script_name.trim() ? { script_name: draft.script_name.trim(), script: draft.script } : {}),
    };
    try { const saved = await backend.saveCustomTool(payload, isNew); setDraft(toDraft(saved)); setIsNew(false); setMessage({ ok: true, text: '已保存。Atlas 下次运行时就能用它。' }); await load(); }
    catch (exc) { fail(exc); }
  };
  const test = async () => {
    if (!draft || isNew) return;
    let args: Record<string, unknown>;
    try { args = JSON.parse(sample || '{}'); } catch { setMessage({ ok: false, text: '示例参数不是合法的 JSON。' }); return; }
    try {
      const result = await backend.testCustomTool(draft.id, args);
      const body = result.error ?? (typeof result.result === 'string' ? result.result : JSON.stringify(result.result, null, 2));
      setMessage({ ok: !result.is_error, text: `退出码 ${result.exit_code ?? '?'}${result.truncated ? '（输出已截断）' : ''}\n${body ?? ''}${result.stderr ? `\n\n错误输出：\n${result.stderr}` : ''}` });
    } catch (exc) { fail(exc); }
  };
  const remove = async () => {
    if (!draft) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try { await backend.deleteCustomTool(draft.id); setDraft(null); setConfirmDelete(false); await load(); } catch (exc) { fail(exc); }
  };

  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const area = cn(field, 'h-auto py-2 font-mono text-[12px] leading-[1.55]');
  return <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-5">
    <nav className="grid content-start gap-1" aria-label="脚本工具列表">
      {tools.map((tool) => <button key={tool.id} onClick={() => { setDraft(toDraft(tool)); setIsNew(false); setMessage(null); setConfirmDelete(false); }} aria-current={draft?.id === tool.id && !isNew}
        className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', draft?.id === tool.id && !isNew ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
        <Wrench size={14} className={cn('shrink-0', tool.enabled ? 'text-brand' : 'text-fg-3')} /><span className="min-w-0 truncate">{tool.name}</span>
      </button>)}
      <button onClick={() => { setDraft(blank()); setIsNew(true); setMessage(null); }} className={cn('flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', isNew ? 'bg-selected text-fg' : 'text-brand hover:bg-hover')}><Plus size={14} />新建工具</button>
    </nav>
    {draft ? <form onSubmit={(event) => void save(event)} className="grid content-start gap-3 text-[13px] text-fg-2">
      <div className="grid grid-cols-2 gap-3">
        <label className="grid gap-1">编号（小写英文、数字、短横线）<input required disabled={!isNew} value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') })} className={field} placeholder="text-stats" /></label>
        <label className="grid gap-1">名称<input required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className={field} placeholder="文字统计" /></label>
      </div>
      <label className="grid gap-1">说明（告诉 Atlas 什么时候用它）<input required value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} className={field} placeholder="统计一段文字的长度并转成大写" /></label>
      <label className="grid gap-1">命令（在工具自己的文件夹里运行）<input required value={draft.commandText} onChange={(event) => setDraft({ ...draft, commandText: event.target.value })} className={cn(field, 'font-mono text-[12.5px]')} /></label>
      <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-3">
        <label className="grid content-start gap-1">脚本文件名<input value={draft.script_name} onChange={(event) => setDraft({ ...draft, script_name: event.target.value })} className={cn(field, 'font-mono text-[12.5px]')} placeholder={isNew ? 'run.py' : '不改就留空'} /></label>
        <label className="grid gap-1">脚本内容{!isNew && <small className="text-fg-3">留空表示不修改已有脚本</small>}<textarea value={draft.script} onChange={(event) => setDraft({ ...draft, script: event.target.value })} rows={7} className={area} /></label>
      </div>
      <label className="grid gap-1">参数格式（JSON Schema）<textarea value={draft.schemaText} onChange={(event) => setDraft({ ...draft, schemaText: event.target.value })} rows={5} className={area} /></label>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">超时（秒）<input type="number" min={1} max={300} value={draft.timeout_s} onChange={(event) => setDraft({ ...draft, timeout_s: Number(event.target.value) || 30 })} className={cn(field, 'w-20')} /></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />启用</label>
      </div>
      <p className="m-0 text-[12px] leading-[1.6] text-fg-3">参数以 JSON 从标准输入传给脚本，脚本打印的内容就是结果（是 JSON 会按 JSON 交给 Atlas）。输出最多 64 KB。脚本工具算作「会动东西」的操作：「改前问我」时会先问你，「只读」时不能用。</p>
      {!isNew && <label className="grid gap-1">用示例参数试跑<textarea value={sample} onChange={(event) => setSample(event.target.value)} rows={2} className={area} /></label>}
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={!draft.id.trim() || !draft.name.trim() || !draft.commandText.trim()}>{isNew ? '创建' : '保存'}</Button>
        {!isNew && <Button onClick={() => void test()}><FlaskConical />试跑</Button>}
        {!isNew && <Button variant={confirmDelete ? 'danger' : 'ghost'} onClick={() => void remove()}><Trash2 />{confirmDelete ? '确认删除' : '删除'}</Button>}
      </div>
      {message && <pre role="status" className={cn('m-0 max-h-60 overflow-auto rounded-lg px-3 py-2 text-[12.5px] whitespace-pre-wrap', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</pre>}
    </form> : <p className="text-[13px] leading-[1.7] text-fg-3">不想写 MCP 服务器，也能给 Atlas 加工具：写一个小脚本，说明它做什么、要什么参数，Atlas 需要时就会调用。{tools.length ? '' : '现在还没有。'}</p>}
  </div>;
}
