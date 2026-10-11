/** Manage only Atlas user-level Markdown slash commands; other sources stay read-only. */
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { FileText, Plus, Save, Trash2 } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { useAtlasStore } from '../../store/useAtlasStore';

type CommandListItem = {
  id: string;
  name: string;
  description?: string | null;
  argument_hint?: string | null;
  source: string;
  source_priority?: number;
  recipe_id?: string | null;
};
type CommandDocument = {
  id: string;
  name: string;
  description: string;
  argument_hint: string;
  body: string;
  source: 'atlas';
};
type Draft = { name: string; description: string; argument_hint: string; body: string };

const NAME = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$/;
const blank = (): Draft => ({ name: '', description: '', argument_hint: '', body: '' });
const sourceLabel = (source: string) => source === 'atlas' ? 'Atlas 用户' : source === 'claude-user' ? 'Claude 用户' : source === 'claude-project' ? 'Claude 项目' : source === 'agents-project' ? '项目 Agent' : source === 'recipe' ? '配方' : source.startsWith('plugin:') ? '插件' : source;

/** Read/write Atlas user command Markdown, with all other discovered commands shown read-only. */
export default function CustomCommandsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const workspace = useAtlasStore((state) => state.conversations.find((item) => item.id === state.activeConversationId)?.workspace);
  const [commands, setCommands] = useState<CommandListItem[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [query, setQuery] = useState('');
  const selected = commands.find((item) => item.id === selectedId) ?? null;
  const manageable = Boolean(selected && selected.source === 'atlas' && NAME.test(selected.name));
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const area = cn(field, 'h-auto py-2 font-mono text-[12px] leading-[1.55]');
  const fail = (error: unknown) => setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) });

  const load = async () => {
    setLoading(true);
    try {
      const suffix = workspace ? `?${new URLSearchParams({ workspace })}` : '';
      const result = await api<{ commands: CommandListItem[] }>(apiBaseUrl, `/api/commands${suffix}`);
      setCommands(result.commands ?? []);
      if (!selectedId && result.commands?.length) setSelectedId(result.commands[0].id);
      return result.commands ?? [];
    } finally { setLoading(false); }
  };
  useEffect(() => { void load().catch(fail); }, [apiBaseUrl, workspace]);
  useEffect(() => {
    setDeleteArmed(false);
    if (isNew) return;
    if (!selected || selected.source !== 'atlas' || !NAME.test(selected.name)) { setDraft(null); return; }
    let current = true;
    setDraft(null);
    setBusy(true);
    api<CommandDocument>(apiBaseUrl, `/api/commands/atlas-user/${encodeURIComponent(selected.name)}`)
      .then((document) => { if (current) setDraft({ name: document.name, description: document.description, argument_hint: document.argument_hint, body: document.body }); })
      .catch((error) => { if (current) fail(error); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [apiBaseUrl, selectedId, commands, isNew]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return commands.filter((item) => !needle || `${item.name} ${item.description ?? ''} ${item.argument_hint ?? ''} ${item.source}`.toLowerCase().includes(needle));
  }, [commands, query]);
  const refreshChatCommands = () => { void useAtlasStore.getState().reloadCommands(workspace || undefined); };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    const name = draft.name.trim();
    if (isNew && !NAME.test(name)) { setMessage({ ok: false, text: '名称需为 1–63 位字母、数字、短横线或下划线，且以字母或数字开头。' }); return; }
    if (!draft.body.trim()) { setMessage({ ok: false, text: '命令正文不能为空。' }); return; }
    setBusy(true);
    try {
      const payload = { ...(isNew ? { name } : {}), description: draft.description, argument_hint: draft.argument_hint, body: draft.body };
      const saved = await api<CommandDocument>(apiBaseUrl, isNew ? '/api/commands/atlas-user' : `/api/commands/atlas-user/${encodeURIComponent(name)}`, { method: isNew ? 'POST' : 'PUT', json: payload });
      setDraft({ name: saved.name, description: saved.description, argument_hint: saved.argument_hint, body: saved.body });
      setIsNew(false); setSelectedId(saved.id); setMessage({ ok: true, text: 'Atlas 用户命令已保存。' });
      await load();
      refreshChatCommands();
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    if (!selected || !manageable) return;
    if (!deleteArmed) { setDeleteArmed(true); return; }
    setBusy(true);
    try {
      await api(apiBaseUrl, `/api/commands/atlas-user/${encodeURIComponent(selected.name)}`, { method: 'DELETE' });
      const remaining = await load();
      setSelectedId(remaining[0]?.id ?? ''); setDraft(null); setMessage({ ok: true, text: 'Atlas 用户命令已删除。' });
      refreshChatCommands();
    } catch (error) { fail(error); }
    finally { setBusy(false); setDeleteArmed(false); }
  };

  return <section className="grid gap-4" aria-label="自定义斜杠命令">
    <header><h2 className="text-[15px] font-semibold text-fg">自定义斜杠命令</h2><p className="mt-1 text-[12.5px] text-fg-3">Atlas 命令保存到用户数据目录的 <code>commands/&lt;name&gt;.md</code>，可在聊天中用 <code>/{'{name}'}</code> 调用。项目、Claude 和插件命令仅在此列出，不会被写入或删除。</p></header>
    <div className="grid grid-cols-[220px_minmax(0,1fr)] gap-5">
      <nav className="grid content-start gap-2" aria-label="可用命令列表">
        <input aria-label="搜索命令" placeholder="搜索命令" value={query} onChange={(event) => setQuery(event.target.value)} className={field} />
        <div className="grid max-h-[28rem] content-start gap-1 overflow-auto">
          {visible.map((command) => <button type="button" key={command.id} onClick={() => { setSelectedId(command.id); setIsNew(false); setMessage(null); }} aria-current={!isNew && selectedId === command.id}
            className={cn('rounded-lg px-2.5 py-2 text-left', !isNew && selectedId === command.id ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover')}>
            <span className="flex items-center gap-1.5 text-[12.5px] font-medium"><FileText size={13} className="shrink-0 text-brand" /><span className="truncate">/{command.name}</span></span>
            <span className="mt-1 block truncate text-[10.5px] text-fg-3">{sourceLabel(command.source)}{command.argument_hint ? ` · ${command.argument_hint}` : ''}</span>
            {command.description && <span className="mt-0.5 block truncate text-[10.5px] text-fg-3">{command.description}</span>}
          </button>)}
          {!visible.length && <p className="px-2 py-3 text-[11.5px] text-fg-3">{loading ? '正在读取命令…' : '没有找到命令。'}</p>}
        </div>
        <Button variant="ghost" size="sm" className="justify-start" onClick={() => { setDraft(blank()); setSelectedId(''); setIsNew(true); setMessage(null); }}><Plus />新建 Atlas 命令</Button>
      </nav>

      {draft ? <form onSubmit={(event) => void save(event)} className="grid content-start gap-3 text-[12.5px] text-fg-2">
        <div className="grid grid-cols-2 gap-3">
          <label className="grid gap-1">命令名称<input required disabled={!isNew} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-') })} className={field} placeholder="review-notes" /><small className="text-fg-3">保存为 {draft.name ? `commands/${draft.name}.md` : 'commands/&lt;name&gt;.md'}</small></label>
          <label className="grid gap-1">参数提示（可选）<input value={draft.argument_hint} onChange={(event) => setDraft({ ...draft, argument_hint: event.target.value })} className={field} placeholder="文件或主题" /></label>
        </div>
        <label className="grid gap-1">说明（可选）<input value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} className={field} placeholder="告诉你这个命令做什么" /></label>
        <label className="grid gap-1">Markdown 命令正文 <small className="text-fg-3">支持 Claude 风格参数占位符，例如 $ARGUMENTS、$1 或 $FILE。</small><textarea required rows={16} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} className={area} placeholder="检查 $ARGUMENTS，并给出简洁的结论。" /></label>
        <div className="flex gap-2"><Button type="submit" variant="primary" disabled={busy}><Save />{busy ? '保存中…' : '保存命令'}</Button>{!isNew && manageable && <Button type="button" variant="danger" disabled={busy} onClick={() => void remove()}><Trash2 />{deleteArmed ? '再次点击确认删除' : '删除'}</Button>}</div>
      </form> : <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-line px-4 text-center text-[12px] text-fg-3">{selected ? <>「/{selected.name}」来自 {sourceLabel(selected.source)}，在这里仅供查看。<br />可管理的 Atlas 用户命令只写入 Atlas 用户数据目录。</> : '选择一个 Atlas 用户命令，或新建命令。'}</div>}
    </div>
    {message && <p role="status" className={cn('whitespace-pre-wrap text-[12px]', message.ok ? 'text-brand' : 'text-danger')}>{message.text}</p>}
  </section>;
}
