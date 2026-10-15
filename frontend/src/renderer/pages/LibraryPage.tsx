import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Download, FolderPlus, Inbox, Library, LoaderCircle, Pencil, Search, Sparkles, Trash2, Wand2, X } from 'lucide-react';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import { cn } from '../ui/cn';
import { libraryApi, type LibraryItem, type LibraryKind, type LibrarySnapshot, type OrganizeReport } from '../services/libraryApi';

const ALL = '__all__';
const UNSORTED = '__unsorted__';
const PAGE = 150;
const BY_LABEL: Record<string, string> = { manual: '手动', declared: '自带', rule: '规则', model: '模型', fallback: '兜底' };
const field = 'rounded-lg bg-sunken px-2.5 py-1.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)]';
const readKind = (): LibraryKind => { try { return localStorage.getItem('atlas.library.kind') === 'tool' ? 'tool' : 'skill'; } catch { return 'skill'; } };

/**
 * 技能与工具库：所有技能 / 工具按分类摆放。新加进来的先进「未整理」，点「一键整理」自动归类，
 * 放不进已有分类的会新建分类；手动改过分类的条目以后整理也不会被挪动。
 */
export default function LibraryPage({ apiBaseUrl, connected, onToast, market }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void; market?: ReactNode }) {
  const api = useMemo(() => libraryApi(apiBaseUrl), [apiBaseUrl]);
  const [kind, setKind] = useState<LibraryKind>(readKind);
  const [showMarket, setShowMarket] = useState(false);
  const [data, setData] = useState<LibrarySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<string>(ALL);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<'all' | 'installed' | 'available'>('all');
  const [limit, setLimit] = useState(PAGE);
  const [organizing, setOrganizing] = useState(false);
  const [report, setReport] = useState<OrganizeReport | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);
  const [envFor, setEnvFor] = useState<LibraryItem | null>(null);

  const refresh = useCallback(() => api.snapshot(kind).then(setData).catch((cause: Error) => onToast(cause.message)).finally(() => setLoading(false)), [api, kind]);
  useEffect(() => { if (connected) { setLoading(true); void refresh(); } }, [connected, refresh]);
  useEffect(() => { try { localStorage.setItem('atlas.library.kind', kind); } catch { /* storage unavailable */ } setCategory(ALL); setLimit(PAGE); }, [kind]);
  useEffect(() => setLimit(PAGE), [category, query, status]);

  const items = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data?.items ?? []).filter((item) =>
      (category === ALL || (category === UNSORTED ? !item.category : item.category === category))
      && (status === 'all' || item.status === status)
      && (!needle || `${item.name} ${item.title ?? ''} ${item.description} ${item.tags.join(' ')}`.toLowerCase().includes(needle)));
  }, [data, category, query, status]);

  const organize = async (full: boolean) => {
    setOrganizing(true);
    try {
      const result = await api.organize(full);
      setReport(result);
      await refresh();
      if (result.model_error) onToast(`模型分类失败，已用规则兜底：${result.model_error}`);
    } catch (cause) { onToast((cause as Error).message); }
    finally { setOrganizing(false); }
  };

  const assign = async (item: LibraryItem, target: string) => {
    try { await api.assign(item.key, target || null); await refresh(); } catch (cause) { onToast((cause as Error).message); }
  };

  const install = async (item: LibraryItem, env: Record<string, string> = {}) => {
    if (item.type === 'tool' && (item.env_required?.length ?? 0) > 0 && !Object.keys(env).length) { setEnvFor(item); return; }
    setInstalling(item.key);
    try {
      if (item.type === 'skill') await api.installSkill(item.name);
      else { const res = await api.installTool(item.name, env); onToast(`已安装 ${item.name}，带来 ${res.tool_count} 个工具`); }
      setEnvFor(null);
      await refresh();
    } catch (cause) { onToast((cause as Error).message); }
    finally { setInstalling(null); }
  };

  const addCategory = async () => {
    const name = window.prompt('新分类的名字');
    if (!name?.trim()) return;
    try { const row = await api.addCategory(name.trim()); await refresh(); setCategory(row.id); } catch (cause) { onToast((cause as Error).message); }
  };
  const renameCategory = async (categoryId: string, current: string) => {
    const name = window.prompt('改成什么名字', current);
    if (!name?.trim() || name.trim() === current) return;
    try { await api.renameCategory(categoryId, name.trim()); await refresh(); } catch (cause) { onToast((cause as Error).message); }
  };
  const deleteCategory = async (categoryId: string, name: string) => {
    if (!window.confirm(`删除分类「${name}」？里面的条目会回到「未整理」，下次一键整理重新归类。`)) return;
    try { await api.deleteCategory(categoryId); setCategory(ALL); await refresh(); } catch (cause) { onToast((cause as Error).message); }
  };

  const categories = (data?.categories ?? []).filter((row) => row.count > 0 || !row.builtin);
  const hidden = (data?.categories.length ?? 0) - categories.length;
  const label = kind === 'skill' ? '技能' : '工具';

  const tabs = <>
    <div className="flex items-center gap-2 px-1">
      <Library size={17} className="text-brand" />
      <h1 className="m-0 flex-1 text-[15px] font-semibold text-heading">技能与工具</h1>
    </div>
    <div className={cn('grid gap-1 rounded-xl bg-sunken p-1', market ? 'grid-cols-3' : 'grid-cols-2')}>
      {(['skill', 'tool'] as const).map((value) => <button key={value} onClick={() => { setKind(value); setShowMarket(false); }}
        className={cn('rounded-lg py-1.5 text-[12.5px]', !showMarket && kind === value ? 'bg-[var(--overlay)] font-medium text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}>
        {value === 'skill' ? '技能库' : '工具库'}</button>)}
      {market && <button onClick={() => setShowMarket(true)} title="在线搜索、安装、更新技能（外部技能先过安全复核）"
        className={cn('rounded-lg py-1.5 text-[12.5px]', showMarket ? 'bg-[var(--overlay)] font-medium text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}>技能市场</button>}
    </div>
  </>;

  if (showMarket && market) {
    return <div className="screen page"><div className="flex h-full min-h-0 gap-4 p-4">
      <aside className="flex w-56 shrink-0 flex-col gap-2">{tabs}
        <p className="m-0 px-1 text-[11.5px] leading-relaxed text-fg-3">从在线市场搜索和安装技能。装好的技能会出现在「技能库」里，点「一键整理」归类。</p>
      </aside>
      <section className="min-w-0 flex-1 overflow-auto rounded-2xl card-surface p-4">{market}</section>
    </div></div>;
  }

  return <div className="screen page"><div className="flex h-full min-h-0 gap-4 p-4">
    <aside className="flex w-56 shrink-0 flex-col gap-2">
      {tabs}
      <div className="grid min-h-0 flex-1 content-start gap-0.5 overflow-auto">
        <CategoryRow active={category === ALL} name={`全部${label}`} count={data?.items.length ?? 0} onClick={() => setCategory(ALL)} />
        {(data?.unorganized ?? 0) > 0 && <CategoryRow active={category === UNSORTED} name="未整理" count={data?.unorganized ?? 0} warn onClick={() => setCategory(UNSORTED)} />}
        <div className="my-1 h-px bg-[var(--line)]" />
        {categories.map((row) => <CategoryRow key={row.id} active={category === row.id} name={row.name} count={row.count} title={row.description}
          isNew={!row.builtin} onClick={() => setCategory(row.id)}
          onRename={() => void renameCategory(row.id, row.name)} onDelete={row.id === 'other' ? undefined : () => void deleteCategory(row.id, row.name)} />)}
        {hidden > 0 && <p className="m-0 px-2 pt-1 text-[11px] text-fg-3">另有 {hidden} 个空的内置分类未显示</p>}
      </div>
      <Button size="sm" variant="ghost" onClick={() => void addCategory()} disabled={!connected}><FolderPlus />新建分类</Button>
    </aside>

    <section className="flex min-w-0 flex-1 flex-col rounded-2xl card-surface p-4">
      <header className="flex flex-wrap items-center gap-2 pb-3 shadow-[inset_0_-1px_0_var(--line)]">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-[15px] font-semibold text-heading">{category === ALL ? `全部${label}` : category === UNSORTED ? '未整理' : data?.categories.find((c) => c.id === category)?.name}</h2>
          <p className="m-0 text-[11.5px] text-fg-3">已安装 {data?.installed ?? 0} · 库里可装 {data?.available ?? 0} · 未整理 {data?.unorganized ?? 0}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setImportOpen(true)} disabled={!connected}><Inbox />导入</Button>
        <Button size="sm" variant="ghost" onClick={() => void organize(true)} disabled={!connected || organizing}
          title="除了手动改过的，全部重新归类一遍（新建分类后想重排时用）">全部重排</Button>
        <Button size="sm" variant="primary" onClick={() => void organize(false)} disabled={!connected || organizing}
          title="把未整理的技能和工具放进合适的分类；没有合适的分类会自动新建">
          {organizing ? <LoaderCircle className="animate-spin" /> : <Wand2 />}一键整理</Button>
      </header>

      {report && <div className="mt-3 flex items-start gap-2 rounded-xl bg-brand-soft px-3 py-2 text-[12.5px] text-fg">
        <Sparkles size={14} className="mt-0.5 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          {report.assigned
            ? <>归类了 {report.assigned} 条（自带分类 {report.by_declared}、规则 {report.by_rule}、模型 {report.by_model}、兜底 {report.by_fallback}），用时 {report.seconds} 秒{report.model === 'off' ? '（没配模型，只用了规则）' : ''}。</>
            : <>没有需要整理的条目。</>}
          {report.new_categories.length > 0 && <> 新建分类：{report.new_categories.map((c) => c.name).join('、')}。</>}
        </div>
        <button aria-label="关闭" onClick={() => setReport(null)} className="text-fg-3 hover:text-fg"><X size={14} /></button>
      </div>}

      <div className="flex flex-wrap items-center gap-2 py-3">
        <label className="flex min-w-[220px] flex-1 items-center gap-2 rounded-lg bg-sunken px-2.5 py-1.5 shadow-[inset_0_0_0_1px_var(--line)]">
          <Search size={14} className="text-fg-3" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`搜索${label}名字、描述、标签`} className="flex-1 bg-transparent text-[13px] text-fg outline-none" />
        </label>
        <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className={field}>
          <option value="all">全部</option><option value="installed">已安装</option><option value="available">库里可装</option>
        </select>
      </div>

      <div className="grid min-h-0 flex-1 content-start gap-1.5 overflow-auto">
        {loading && <p className="m-0 flex items-center gap-2 text-[12.5px] text-fg-3"><LoaderCircle size={13} className="animate-spin" />加载中…</p>}
        {!loading && !items.length && <div className="rounded-xl bg-sunken p-4 text-[12.5px] leading-relaxed text-fg-2">
          {data?.items.length ? '没有符合条件的条目。' : <>库还是空的。把网页 GPT 搜罗出的 JSONL 文件放进<br /><code className="font-mono text-[11.5px]">{data?.inbox}</code><br />再点「导入」→「从收件箱导入」，然后「一键整理」。</>}
        </div>}
        {items.slice(0, limit).map((item) => <ItemRow key={item.key} item={item} categories={data?.categories ?? []}
          installing={installing === item.key} onAssign={(target) => void assign(item, target)} onInstall={() => void install(item)} />)}
        {items.length > limit && <Button size="sm" variant="ghost" onClick={() => setLimit((n) => n + PAGE)}>再显示 {Math.min(PAGE, items.length - limit)} 条（共 {items.length}）</Button>}
      </div>
    </section>

    <ImportDialog open={importOpen} onOpenChange={setImportOpen} inbox={data?.inbox ?? ''} api={api} onToast={onToast}
      onDone={async () => { await refresh(); setCategory(UNSORTED); }} />
    <EnvDialog item={envFor} busy={!!installing} onClose={() => setEnvFor(null)} onSubmit={(env) => envFor && void install(envFor, env)} />
  </div></div>;
}

function CategoryRow({ name, count, active, warn, isNew, title, onClick, onRename, onDelete }: {
  name: string; count: number; active: boolean; warn?: boolean; isNew?: boolean; title?: string;
  onClick: () => void; onRename?: () => void; onDelete?: () => void;
}) {
  return <div className={cn('group flex items-center gap-1 rounded-lg px-2 py-1.5', active ? 'bg-selected' : 'hover:bg-hover')} title={title}>
    <button onClick={onClick} className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[12.5px] text-fg">
      <span className="truncate">{name}</span>
      {isNew && <span className="shrink-0 rounded bg-brand-soft px-1 text-[10px] text-brand">新</span>}
    </button>
    {onRename && <button aria-label="重命名" onClick={onRename} className="hidden size-5 place-items-center rounded text-fg-3 group-hover:grid hover:text-fg"><Pencil size={11} /></button>}
    {onDelete && <button aria-label="删除分类" onClick={onDelete} className="hidden size-5 place-items-center rounded text-fg-3 group-hover:grid hover:text-danger"><Trash2 size={11} /></button>}
    <span className={cn('shrink-0 text-[11px] tabular-nums', warn ? 'font-semibold text-brand' : 'text-fg-3')}>{count}</span>
  </div>;
}

function ItemRow({ item, categories, installing, onAssign, onInstall }: {
  item: LibraryItem; categories: LibrarySnapshot['categories']; installing: boolean; onAssign: (category: string) => void; onInstall: () => void;
}) {
  return <div className="flex items-start gap-3 rounded-xl px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]">
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[12.5px] font-medium text-fg">{item.name}</span>
        {item.title && <span className="text-[12.5px] text-fg-2">{item.title}</span>}
        {item.status === 'installed'
          ? <span className="rounded bg-ok-soft px-1 text-[10.5px] text-ok">已安装</span>
          : <span className="rounded bg-sunken px-1 text-[10.5px] text-fg-3">库里可装</span>}
        {item.kind === 'mcp' && <span className="rounded bg-sunken px-1 text-[10.5px] text-fg-3">MCP{item.server ? ` · ${item.server}` : ''}</span>}
        {item.official && <span className="rounded bg-brand-soft px-1 text-[10.5px] text-brand">官方</span>}
        {item.windows === false && <span className="rounded bg-danger-soft px-1 text-[10.5px] text-danger">不支持 Windows</span>}
      </div>
      <p className="m-0 mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-fg-2">{item.description}</p>
      <p className="m-0 mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-fg-3">
        {item.source && <span>{item.source}</span>}
        {item.stars != null && <span>★ {item.stars}</span>}
        {item.last_updated && <span>更新于 {item.last_updated}</span>}
        {item.env_required && item.env_required.length > 0 && <span>需要 {item.env_required.join('、')}</span>}
        {item.homepage && <a href={item.homepage} target="_blank" rel="noreferrer" className="text-brand hover:underline">主页</a>}
      </p>
    </div>
    <div className="flex shrink-0 flex-col items-end gap-1.5">
      <select value={item.category ?? ''} onChange={(e) => onAssign(e.target.value)} className="max-w-[150px] rounded-md bg-sunken px-1.5 py-0.5 text-[12px] text-fg-2"
        title={item.assigned_by ? `归类方式：${BY_LABEL[item.assigned_by] ?? item.assigned_by}` : '还没整理'}>
        <option value="">未整理</option>
        {categories.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
      </select>
      {item.status === 'available' && item.kind !== 'cli' && <Button size="sm" variant="secondary" disabled={installing} onClick={onInstall}
        title={item.type === 'skill' ? '下载到本地；不装也行，Atlas 用到时会自动下载' : '添加为 MCP 服务器'}>
        {installing ? <LoaderCircle className="animate-spin" /> : <Download />}安装</Button>}
    </div>
  </div>;
}

function ImportDialog({ open, onOpenChange, inbox, api, onToast, onDone }: {
  open: boolean; onOpenChange: (open: boolean) => void; inbox: string; api: ReturnType<typeof libraryApi>;
  onToast: (text: string) => void; onDone: () => Promise<void>;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string>('');
  const run = async (fromInbox: boolean) => {
    setBusy(true); setResult('');
    try {
      const res = fromInbox ? await api.importInbox() : await api.importText(text);
      setResult(`${fromInbox ? `读了 ${res.files ?? 0} 个文件，` : ''}新增 ${res.added} 条，更新 ${res.updated} 条，库里共 ${res.total} 条。`
        + (res.errors.length ? `\n跳过 ${res.errors.length} 处：\n${res.errors.slice(0, 12).join('\n')}` : ''));
      if (!fromInbox) setText('');
      await onDone();
    } catch (cause) { onToast((cause as Error).message); }
    finally { setBusy(false); }
  };
  return <Dialog open={open} onOpenChange={onOpenChange} label="导入技能和工具" className="w-[min(640px,94vw)]">
    <div className="grid gap-3 bg-[var(--overlay)] p-5">
      <h2 className="m-0 text-[15px] font-semibold text-heading">导入技能和工具</h2>
      <p className="m-0 text-[12.5px] leading-relaxed text-fg-2">把网页 GPT 按任务书交付的 <code>skills-*.jsonl</code>、<code>tools-*.jsonl</code> 放进收件箱再点「从收件箱导入」，或者直接把内容粘到下面。导入后条目进「未整理」，点「一键整理」归类。</p>
      <code className="break-all rounded-lg bg-sunken px-2.5 py-1.5 font-mono text-[11.5px] text-fg-2">{inbox}</code>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} placeholder='{"type": "skill", "name": "...", ...}（每行一条）'
        className={cn(field, 'font-mono text-[12px]')} />
      {result && <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-sunken p-2.5 text-[12px] text-fg-2">{result}</pre>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => onOpenChange(false)}>关闭</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void run(true)}><Inbox />从收件箱导入</Button>
        <Button variant="primary" disabled={busy || !text.trim()} onClick={() => void run(false)}>{busy ? <LoaderCircle className="animate-spin" /> : null}导入粘贴的内容</Button>
      </div>
    </div>
  </Dialog>;
}

function EnvDialog({ item, busy, onClose, onSubmit }: { item: LibraryItem | null; busy: boolean; onClose: () => void; onSubmit: (env: Record<string, string>) => void }) {
  const [env, setEnv] = useState<Record<string, string>>({});
  useEffect(() => setEnv({}), [item?.key]);
  const keys = item?.env_required ?? [];
  return <Dialog open={!!item} onOpenChange={(open) => { if (!open) onClose(); }} label="填写工具需要的密钥" className="w-[min(480px,94vw)]">
    <div className="grid gap-3 bg-[var(--overlay)] p-5">
      <h2 className="m-0 text-[15px] font-semibold text-heading">安装 {item?.name}</h2>
      <p className="m-0 text-[12.5px] text-fg-2">这个工具需要下面这些环境变量，只保存在本机的 Atlas 配置里。</p>
      {keys.map((key) => <label key={key} className="grid gap-1 text-[12.5px] text-fg-2">{key}
        <input type="password" value={env[key] ?? ''} onChange={(e) => setEnv((m) => ({ ...m, [key]: e.target.value }))} className={field} /></label>)}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>取消</Button>
        <Button variant="primary" disabled={busy || keys.some((key) => !env[key]?.trim())} onClick={() => onSubmit(env)}>
          {busy ? <LoaderCircle className="animate-spin" /> : <Download />}安装</Button>
      </div>
    </div>
  </Dialog>;
}
