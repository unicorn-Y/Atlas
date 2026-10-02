import { useEffect, useState } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import type { LspServerStatus } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { cn } from '../ui/cn';

/** 设置 → 高级：这台电脑上的语言服务（LSP）是否就绪，改文件后 Atlas 靠它们报告新问题。 */
export default function LspStatusSection({ workspace, connected }: { workspace: string; connected: boolean }) {
  const [servers, setServers] = useState<LspServerStatus[] | null>(null);
  const [error, setError] = useState('');
  const [reloading, setReloading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    if (!connected || !workspace) { setServers([]); return; }
    let stale = false;
    setServers(null);
    setReloading(true);
    backend.getLspStatus(workspace)
      .then((result) => { if (!stale) { setServers(result.servers); setError(''); } })
      .catch((exc) => { if (!stale) { setServers([]); setError(exc instanceof Error ? exc.message : String(exc)); } })
      .finally(() => { if (!stale) setReloading(false); });
    return () => { stale = true; };
  }, [connected, workspace, reloadKey]);

  return <section aria-label="语言服务（LSP）">
    <div className="flex items-center gap-2">
      <h3 className="m-0 text-[15px] font-semibold text-heading">语言服务（LSP）</h3>
      <span className="flex-1" />
      <button aria-label="重新探测语言服务" disabled={!connected || !workspace || reloading} onClick={() => setReloadKey((value) => value + 1)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-40">
        {reloading ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}重新探测
      </button>
    </div>
    <p className="m-0 mt-1 mb-3 text-[13px] text-fg-3">Atlas 改完文件后，语言服务会立刻指出新引入的问题。没装的服务不会拖慢任务，只是少了这一层检查。</p>
    {!connected ? <p className="m-0 text-[13px] text-fg-3">后端没有连接。</p>
      : !workspace ? <p className="m-0 text-[13px] text-fg-3">先在对话里选好工作目录，这里会显示这台电脑上的语言服务。</p>
      : servers === null ? <p className="m-0 text-[13px] text-fg-3">正在探测…</p>
      : <>
        {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
        {servers.length ? <ul className="m-0 grid list-none gap-1.5 p-0">
          {servers.map((server) => <li key={server.id} className="flex items-start gap-2.5 rounded-xl card-surface px-3 py-2.5 text-[13px]">
            <span aria-label={server.available ? '已就绪' : '未安装'} className={cn('mt-[7px] size-2 shrink-0 rounded-full', server.available ? 'bg-ok' : 'bg-fg-3')} />
            <span className="min-w-0 flex-1">
              <span className="text-fg">{server.id}</span>
              {server.languages.length > 0 && <span className="ml-2 text-[12px] text-fg-3">{server.languages.join('、')}</span>}
              <small className="block text-[12px] text-fg-3">{server.available ? '已就绪' : server.hint ? `未安装：${server.hint}` : '未安装'}</small>
            </span>
          </li>)}
        </ul> : !error && <p className="m-0 text-[13px] text-fg-3">后端没有报告可用的语言服务。</p>}
      </>}
  </section>;
}
