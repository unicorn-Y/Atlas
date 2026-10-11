import { useEffect, useMemo, useState } from 'react';
import { Download, FileCode2, LoaderCircle, Package, RefreshCw, Search, X } from 'lucide-react';
import { Button } from '../../ui/Button';
import { Dialog } from '../../ui/Dialog';
import { cn } from '../../ui/cn';
import type { RegistryAgent, WorkbenchAgent, WorkbenchApi } from '../../services/workbenchApi';
import { ManifestForm, draftOf, manifestOf, type ManifestDraft } from './AgentSettings';

type Tab = 'registry' | 'custom' | 'template';
const INSTALL_LABEL = { npx: 'npm 包', uvx: 'Python 包', binary: '下载程序' } as const;

/** 添加挂件：从 ACP 注册表挑、填自定义命令、或从模板写自己的 agent。 */
export default function AddAgentDialog({ api, open, onOpenChange, onAdded, onToast }: {
  api: WorkbenchApi; open: boolean; onOpenChange: (open: boolean) => void;
  onAdded: (agent: WorkbenchAgent) => void; onToast: (text: string) => void;
}) {
  const [tab, setTab] = useState<Tab>('registry');
  const [registry, setRegistry] = useState<RegistryAgent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [installing, setInstalling] = useState('');
  const [draft, setDraft] = useState<ManifestDraft>(draftOf());
  const [templateName, setTemplateName] = useState('');
  const [busy, setBusy] = useState(false);

  const load = (refresh = false) => {
    setLoading(true); setError('');
    api.registry(refresh).then((data) => setRegistry(data.agents)).catch((cause: Error) => setError(cause.message)).finally(() => setLoading(false));
  };
  useEffect(() => { if (open && tab === 'registry' && !registry.length) load(); }, [open, tab]);
  useEffect(() => { if (open) { setDraft(draftOf()); setTemplateName(''); } }, [open]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return registry.filter((item) => !q || `${item.name} ${item.id} ${item.description}`.toLowerCase().includes(q))
      .sort((a, b) => Number(!a.install) - Number(!b.install));
  }, [registry, query]);

  const install = async (item: RegistryAgent) => {
    setInstalling(item.id);
    try { const agent = await api.install(item.id); onAdded(agent); onToast(`已装上「${agent.name}」`); onOpenChange(false); }
    catch (cause) { onToast((cause as Error).message); }
    finally { setInstalling(''); }
  };
  const create = async () => {
    setBusy(true);
    try {
      const agent = tab === 'template' ? await api.createTemplate(templateName.trim()) : await api.create(manifestOf(draft));
      onAdded(agent); onToast(`已添加「${agent.name}」`); onOpenChange(false);
    } catch (cause) { onToast((cause as Error).message); }
    finally { setBusy(false); }
  };

  return <Dialog open={open} onOpenChange={onOpenChange} label="添加挂件" className="w-[min(720px,94vw)]">
    <div className="flex h-[min(680px,86vh)] flex-col bg-[var(--overlay)]">
      <div className="flex items-center gap-2 px-5 pt-4 pb-3">
        <h2 className="m-0 flex-1 text-[15px] font-semibold text-heading">添加挂件</h2>
        <Button size="icon-sm" variant="ghost" aria-label="关闭" onClick={() => onOpenChange(false)}><X /></Button>
      </div>
      <div className="flex gap-1 px-5 pb-3 shadow-[inset_0_-1px_0_var(--line)]">
        {([['registry', '从 ACP 注册表', Package], ['custom', '自定义命令', FileCode2], ['template', '自己写一个', FileCode2]] as const).map(([value, label, Icon]) =>
          <button key={value} onClick={() => setTab(value)} className={cn('inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[13px]', tab === value ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover')}><Icon size={14} />{label}</button>)}
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        {tab === 'registry' && <>
          <div className="mb-3 flex items-center gap-2">
            <div className="flex flex-1 items-center gap-2 rounded-lg bg-sunken px-2.5 py-1.5 shadow-[inset_0_0_0_1px_var(--line)]">
              <Search size={14} className="text-fg-3" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索 agent" className="flex-1 bg-transparent text-[13px] outline-none" />
            </div>
            <Button size="sm" variant="ghost" onClick={() => load(true)} disabled={loading}><RefreshCw className={loading ? 'animate-spin' : undefined} />刷新</Button>
          </div>
          {error && <p className="m-0 mb-3 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
          {loading && !registry.length && <p className="m-0 flex items-center gap-2 text-[13px] text-fg-3"><LoaderCircle size={14} className="animate-spin" />正在读注册表…</p>}
          <div className="grid gap-2 sm:grid-cols-2">{shown.map((item) =>
            <div key={item.id} className={cn('flex gap-3 rounded-xl card-surface p-3', !item.install && 'opacity-55')}>
              {item.icon ? <img src={item.icon} alt="" className="size-8 shrink-0 rounded-lg bg-white p-1" /> : <Package size={28} className="shrink-0 text-fg-3" />}
              <div className="min-w-0 flex-1">
                <p className="m-0 truncate text-[13.5px] font-semibold text-fg">{item.name} <span className="font-normal text-fg-3">{item.version}</span></p>
                <p className="m-0 line-clamp-2 text-[12px] text-fg-2">{item.description}</p>
                <div className="mt-2 flex items-center gap-2">
                  {item.install
                    ? <Button size="sm" variant="secondary" disabled={!!installing} onClick={() => void install(item)}>
                        {installing === item.id ? <LoaderCircle className="animate-spin" /> : <Download />}装上</Button>
                    : <span className="text-[11.5px] text-fg-3">这台电脑上没有可用的安装包</span>}
                  {item.install && <span className="text-[11.5px] text-fg-3">{INSTALL_LABEL[item.install]}</span>}
                </div>
              </div>
            </div>)}</div>
          <p className="m-0 mt-4 text-[11.5px] text-fg-3">来自 agentclientprotocol.com 官方注册表。装上时版本就钉死了，之后只有你在挂件设置里点「升级」才会换。同一个 agent 可以装多份，各干各的。</p>
        </>}
        {tab === 'custom' && <ManifestForm draft={draft} onChange={setDraft} />}
        {tab === 'template' && <div className="grid gap-3 text-[13px] text-fg-2">
          <p className="m-0">生成一个最小的 Python ACP agent（几十行），放在它自己的文件夹里。改里面的 <code>handle()</code> 就是改它的本事；模型地址和密钥填在它自己的环境变量里，和 Atlas 主体的模型配置互不相干。</p>
          <label className="grid gap-1 text-[12.5px]">名字<input value={templateName} onChange={(e) => setTemplateName(e.target.value)} placeholder="例如 周报助手"
            className="rounded-lg bg-sunken px-2.5 py-1.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)]" /></label>
        </div>}
      </div>
      {tab !== 'registry' && <div className="flex justify-end gap-2 px-5 py-3 shadow-[inset_0_1px_0_var(--line)]">
        <Button size="sm" variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
        <Button size="sm" variant="primary" disabled={busy || (tab === 'template' ? !templateName.trim() : !draft.name.trim() || !draft.command.trim())} onClick={() => void create()}>添加</Button>
      </div>}
    </div>
  </Dialog>;
}
