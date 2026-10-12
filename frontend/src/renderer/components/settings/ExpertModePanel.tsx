import { useEffect, useState } from 'react';
import { FolderOpen, Plus, RefreshCw, Zap } from 'lucide-react';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

type Kind = 'prompts' | 'skills' | 'plugins' | 'tools' | 'mcp';
interface ExpertItem { name: string; installed: boolean; description: string; editable: boolean }
interface GitState { ready: boolean; changes: number; ahead: number; behind: number; remote: string; last_commit?: string }
interface ExpertStatus {
  enabled: boolean; dir: string; repo: string; items: Record<Kind, ExpertItem[]>;
  config_text: string; overlay_sections: string[]; config_error: string; git: GitState;
}
interface SyncResult { status: string; message: string; files?: string[] }

const EVENT = 'atlas:expert-mode';

async function call<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

const area = 'w-full rounded-lg bg-sunken px-2.5 py-2 font-mono text-[12.5px] leading-[1.55] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
const field = 'h-8 rounded-lg bg-sunken px-2.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

const TABS: { id: Kind | 'config'; label: string; hint: string }[] = [
  { id: 'prompts', label: '提示词', hint: '装上的按名字顺序拼到系统提示词末尾。' },
  { id: 'skills', label: '技能', hint: '和普通技能同格式（SKILL.md）；名字只能用小写字母、数字、连字符，同名时这里的优先。' },
  { id: 'plugins', label: '插件', hint: '和普通插件同格式，多文件的请点「打开文件夹」放进去。' },
  { id: 'tools', label: '工具', hint: '和自定义工具同格式（tool.json + 脚本），编号只能用小写字母、数字、连字符。' },
  { id: 'mcp', label: 'MCP', hint: '每项一个 MCP 服务器，字段同 atlas.toml 的 [tools.servers.x]。' },
  { id: 'config', label: '配置覆盖', hint: '和 atlas.toml 同写法，只写要改的部分，按小节深度合并。' },
];

/** 设置 → 专家模式：开关、仓库同步，以及仓库里各项的编辑和装卸。 */
export default function ExpertModePanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const [status, setStatus] = useState<ExpertStatus | null>(null);
  const [tab, setTab] = useState<Kind | 'config'>('prompts');
  const [filter, setFilter] = useState<'all' | 'on' | 'off'>('all');
  const [editing, setEditing] = useState<{ kind: Kind; name: string; text: string; original: string } | null>(null);
  const [newName, setNewName] = useState('');
  const [configText, setConfigText] = useState('');
  const [conflict, setConflict] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = (next: ExpertStatus) => {
    setStatus(next); setConfigText(next.config_text);
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next.enabled }));
  };
  useEffect(() => { void call<ExpertStatus>(apiBaseUrl, '/api/expert-mode').then(apply).catch((cause: Error) => onToast(cause.message)); }, [apiBaseUrl]);

  const run = async (work: () => Promise<ExpertStatus | void>, done?: string) => {
    setBusy(true);
    try { const next = await work(); if (next) apply(next); if (done) onToast(done); return true; }
    catch (cause) { onToast((cause as Error).message); return false; }
    finally { setBusy(false); }
  };
  const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
  const item = (kind: Kind, name: string) => `/api/expert-mode/items/${kind}/${encodeURIComponent(name)}`;

  const toggle = () => run(() => call(apiBaseUrl, '/api/expert-mode/toggle', json('POST', { enabled: !status?.enabled })),
    status?.enabled ? '已切回普通模式' : '已切到专家模式');
  const install = (kind: Kind, entry: ExpertItem) => run(() => call(apiBaseUrl, `${item(kind, entry.name)}/install`, json('POST', { installed: !entry.installed })),
    entry.installed ? `已卸载「${entry.name}」，文件还在仓库里` : `已安装「${entry.name}」`);
  const openEditor = async (kind: Kind, name: string) => {
    try {
      const data = await call<{ text: string }>(apiBaseUrl, item(kind, name));
      setEditing({ kind, name, text: data.text, original: data.text });
    } catch (cause) { onToast((cause as Error).message); }
  };
  const create = async (kind: Kind) => {
    const name = newName.trim();
    if (!name) return;
    if (await run(() => call(apiBaseUrl, item(kind, name), json('POST', {})), `已新建并安装「${name}」`)) {
      setNewName('');
      void openEditor(kind, name);
    }
  };
  const saveEditor = () => editing && run(async () => {
    const next = await call<ExpertStatus>(apiBaseUrl, item(editing.kind, editing.name), json('PUT', { text: editing.text }));
    setEditing(null); return next;
  }, '已保存，下一轮对话生效');
  const remove = (kind: Kind, name: string) => {
    if (!window.confirm(`从仓库里删除「${name}」？\n只想不用的话点「卸载」就行；删除后再同步，仓库里也会删掉（git 历史里还找得回）。`)) return;
    void run(() => call(apiBaseUrl, item(kind, name), json('DELETE')), `已删除「${name}」`);
  };
  const openFolder = (kind = '', name = '') => {
    const query = new URLSearchParams({ kind, name }).toString();
    void call(apiBaseUrl, `/api/expert-mode/open?${query}`, json('POST')).catch((cause: Error) => onToast(cause.message));
  };
  const saveConfig = () => run(() => call(apiBaseUrl, '/api/expert-mode/overlay', json('PUT', { config_text: configText })), '已保存');
  const sync = (prefer?: 'local' | 'remote') => run(async () => {
    const data = await call<{ result: SyncResult; status: ExpertStatus }>(apiBaseUrl, '/api/expert-mode/sync', json('POST', { prefer: prefer ?? null }));
    setConflict(data.result.status === 'conflict' ? data.result.files ?? [] : null);
    onToast(data.result.message);
    return data.status;
  });

  if (!status) return <p className="m-0 text-[13px] text-fg-3">加载中…</p>;
  const current = TABS.find((entry) => entry.id === tab)!;
  const items = tab === 'config' ? [] : status.items[tab].filter((entry) => filter === 'all' || (filter === 'on') === entry.installed);
  const git = status.git;
  const gitLine = !git.ready ? '还没准备好（点一次同步会自动建好）'
    : [git.changes ? `本机有 ${git.changes} 处没同步` : '', git.ahead ? `待推送 ${git.ahead} 个提交` : '', git.behind ? `仓库有 ${git.behind} 个新提交` : '',
      git.last_commit ? `最近提交 ${git.last_commit}` : ''].filter(Boolean).join(' · ') || '已是最新';

  return <div className="grid gap-5">
    <div className={cn('flex items-center gap-3 rounded-xl px-4 py-3', status.enabled ? 'bg-brand-soft' : 'bg-sunken')}>
      <Zap size={18} className={status.enabled ? 'text-brand' : 'text-fg-3'} />
      <div className="flex-1 text-[13px]">
        <p className="m-0 font-semibold text-fg">{status.enabled ? '专家模式已开启' : '现在是普通模式'}</p>
        <p className="m-0 text-[12px] text-fg-3">开启后额外加载下面「已安装」的内容；关掉后全部不加载，普通配置原样不动。切换和装卸都即时生效。</p>
      </div>
      <Button variant={status.enabled ? 'secondary' : 'primary'} disabled={busy} onClick={() => void toggle()}>{status.enabled ? '切回普通模式' : '切到专家模式'}</Button>
    </div>

    <div className="grid gap-2 rounded-xl bg-sunken px-4 py-3 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-fg">内容仓库</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-fg-3" title={status.dir}>{status.dir}</span>
        <Button size="sm" variant="ghost" onClick={() => openFolder()}><FolderOpen />打开目录</Button>
        <Button size="sm" variant="primary" disabled={busy} onClick={() => void sync()}><RefreshCw className={cn(busy && 'animate-spin')} />同步</Button>
      </div>
      <p className="m-0 text-[12px] text-fg-3">{gitLine}{git.remote ? ` · ${git.remote}` : ''}</p>
      <p className="m-0 text-[12px] text-fg-3">同步 = 提交本机改动、拉取仓库、再推上去。新拉下来的内容默认不安装，在下面挑着装。</p>
      {conflict && <div className="grid gap-2 rounded-lg bg-danger-soft px-3 py-2 text-danger">
        <p className="m-0">本机和仓库都改了这些文件：{conflict.join('、') || '（未知）'}。选一边保留：</p>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void sync('local')}>保留本机的</Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void sync('remote')}>用仓库里的</Button>
          <Button size="sm" variant="ghost" onClick={() => setConflict(null)}>先不处理</Button>
        </div>
      </div>}
    </div>

    <div className="grid gap-3">
      <div className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((entry) => {
          const list = entry.id === 'config' ? null : status.items[entry.id];
          return <button key={entry.id} type="button" onClick={() => { setTab(entry.id); setEditing(null); }}
            className={cn('-mb-px border-b-2 px-3 py-1.5 text-[13px]', tab === entry.id ? 'border-brand font-semibold text-fg' : 'border-transparent text-fg-3 hover:text-fg')}>
            {entry.label}{list ? <span className="ml-1 text-[11.5px] text-fg-3">{list.filter((i) => i.installed).length}/{list.length}</span> : null}
          </button>;
        })}
      </div>
      <p className="m-0 text-[12px] text-fg-3">{current.hint}</p>

      {tab === 'config' ? <div className="grid gap-1.5">
        <textarea className={area} rows={12} spellCheck={false} value={configText} onChange={(event) => setConfigText(event.target.value)}
          placeholder={'# 例如\n[models]\ndefault = "某个模型"'} />
        {status.config_error && <span className="text-[12px] text-danger">现有文件写法有错，没有生效：{status.config_error}</span>}
        {!!status.overlay_sections.length && <span className="text-[12px] text-fg-3">会覆盖的小节：{status.overlay_sections.join('、')}</span>}
        <span className="text-[12px] text-fg-3">模型网关等启动时读取的项要重启 Atlas 才生效；其余下一轮对话起生效。</span>
        <div className="flex justify-end gap-2">
          {configText !== status.config_text && <Button variant="ghost" onClick={() => setConfigText(status.config_text)}>撤销修改</Button>}
          <Button variant="primary" disabled={configText === status.config_text || busy} onClick={() => void saveConfig()}>保存</Button>
        </div>
      </div> : editing ? <div className="grid gap-1.5">
        <span className="text-[12.5px] font-semibold text-fg">编辑「{editing.name}」</span>
        <textarea className={area} rows={18} spellCheck={false} value={editing.text} onChange={(event) => setEditing({ ...editing, text: event.target.value })} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => openFolder(editing.kind, editing.name)}><FolderOpen />打开文件夹</Button>
          <Button variant="ghost" onClick={() => setEditing(null)}>{editing.text === editing.original ? '返回' : '放弃修改'}</Button>
          <Button variant="primary" disabled={editing.text === editing.original || busy} onClick={() => void saveEditor()}>保存</Button>
        </div>
      </div> : <>
        <div className="flex flex-wrap items-center gap-2">
          <input className={cn(field, 'w-48')} value={newName} placeholder={tab === 'tools' ? '新工具编号，如 my-tool' : tab === 'skills' ? '技能名，如 my-skill' : '新建一项的名字'}
            onChange={(event) => setNewName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void create(tab); }} />
          <Button size="sm" variant="secondary" disabled={!newName.trim() || busy} onClick={() => void create(tab)}><Plus />新建</Button>
          <div className="ml-auto flex gap-1">
            {(['all', 'on', 'off'] as const).map((value) => <Button key={value} size="sm" variant={filter === value ? 'secondary' : 'ghost'} onClick={() => setFilter(value)}>
              {{ all: '全部', on: '已安装', off: '未安装' }[value]}
            </Button>)}
          </div>
        </div>
        {!items.length && <p className="m-0 rounded-lg bg-sunken px-3 py-4 text-center text-[12.5px] text-fg-3">这里还没有内容。新建一项，或者放进仓库目录后点「同步」。</p>}
        <ul className="m-0 grid list-none gap-1.5 p-0">
          {items.map((entry) => <li key={entry.name} className="flex items-center gap-3 rounded-lg bg-sunken px-3 py-2">
            <span className={cn('size-2 shrink-0 rounded-full', entry.installed ? 'bg-brand' : 'bg-line')} />
            <div className="min-w-0 flex-1">
              <p className="m-0 truncate text-[13px] font-medium text-fg">{entry.name}</p>
              {entry.description && <p className="m-0 truncate text-[12px] text-fg-3">{entry.description}</p>}
            </div>
            <Button size="sm" variant={entry.installed ? 'secondary' : 'primary'} disabled={busy} onClick={() => void install(tab, entry)}>{entry.installed ? '卸载' : '安装'}</Button>
            {entry.editable && <Button size="sm" variant="ghost" onClick={() => void openEditor(tab, entry.name)}>编辑</Button>}
            <Button size="icon-sm" variant="ghost" title="打开文件夹" onClick={() => openFolder(tab, entry.name)}><FolderOpen /></Button>
            <Button size="sm" variant="ghost" className="text-danger" disabled={busy} onClick={() => remove(tab, entry.name)}>删除</Button>
          </li>)}
        </ul>
      </>}
    </div>
  </div>;
}

/** 专家模式开着、又不在聊天界面时，窗口右上角挂着的提醒。 */
export function ExpertModeBadge({ apiBaseUrl, onOpen }: { apiBaseUrl: string; onOpen: () => void }) {
  const [enabled] = useExpertMode(apiBaseUrl);
  if (!enabled) return null;
  return <button onClick={onOpen} title="专家模式已开启，点这里查看或关闭"
    className="fixed top-2 right-36 z-40 inline-flex items-center gap-1 rounded-full bg-brand px-2.5 py-0.5 text-[11.5px] font-semibold text-white shadow-md [-webkit-app-region:no-drag]">
    <Zap size={12} className="fill-current" />专家模式
  </button>;
}

/** 专家模式当前是否开启；各处的开关、角标共用同一个事件保持同步。 */
export function useExpertMode(apiBaseUrl: string): [boolean, (enabled: boolean) => Promise<void>] {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    void call<ExpertStatus>(apiBaseUrl, '/api/expert-mode').then((s) => setEnabled(s.enabled)).catch(() => undefined);
    const listener = (event: Event) => setEnabled(Boolean((event as CustomEvent<boolean>).detail));
    window.addEventListener(EVENT, listener);
    return () => window.removeEventListener(EVENT, listener);
  }, [apiBaseUrl]);
  const toggle = async (next: boolean) => {
    const status = await call<ExpertStatus>(apiBaseUrl, '/api/expert-mode/toggle', { method: 'POST', body: JSON.stringify({ enabled: next }) });
    window.dispatchEvent(new CustomEvent(EVENT, { detail: status.enabled }));
  };
  return [enabled, toggle];
}

/** 打开设置里的专家模式页（App 监听）。 */
export const OPEN_EXPERT_SETTINGS = 'atlas:open-expert-settings';

/** 输入框工具栏上的专家模式开关：点一下切换，右键打开设置。 */
export function ExpertModeToggle({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [enabled, toggle] = useExpertMode(apiBaseUrl);
  const [busy, setBusy] = useState(false);
  const flip = async () => { setBusy(true); try { await toggle(!enabled); } catch { /* backend offline: state unchanged */ } finally { setBusy(false); } };
  return <button type="button" role="switch" aria-checked={enabled} aria-label={enabled ? '关闭专家模式' : '开启专家模式'} disabled={busy}
    title={enabled ? '专家模式已开启：点击切回普通模式，右键编辑专家配置' : '切到专家模式（右键编辑专家配置）'}
    onClick={() => void flip()}
    onContextMenu={(event) => { event.preventDefault(); window.dispatchEvent(new Event(OPEN_EXPERT_SETTINGS)); }}
    className={cn('inline-flex h-8 shrink-0 items-center gap-1 rounded-full text-[12px] font-medium transition-all duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-60',
      enabled ? 'min-w-8 justify-center bg-brand-soft px-2 text-brand @[640px]:px-2.5' : 'w-8 justify-center text-fg-3 hover:bg-hover hover:text-fg')}>
    <Zap size={15} className={cn('transition-transform', enabled && 'fill-current')} />
    {enabled && <span className="hidden @[640px]:inline">专家</span>}
  </button>;
}
