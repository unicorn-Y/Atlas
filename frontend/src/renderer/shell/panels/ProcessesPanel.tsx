import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Square } from 'lucide-react';
import type { ProcessInfo } from '@atlas/backend-adapter';
import { backend } from '../../store/useAtlasStore';
import { Empty } from './Empty';

export default function ProcessesPanel({ onToast }: { onToast: (text: string) => void }) {
  const [items, setItems] = useState<ProcessInfo[]>([]);
  const [outputs, setOutputs] = useState<Record<string, string>>({});
  const refresh = useCallback(async () => {
    try { setItems(await backend.getProcesses()); } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
  }, [onToast]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 3000); return () => window.clearInterval(timer); }, [refresh]);
  const readOutput = async (id: string) => {
    try { const value = await backend.getProcessOutput(id); setOutputs((current) => ({ ...current, [id]: value.output || '(暂无输出)' })); }
    catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
  };
  const stop = async (item: ProcessInfo) => {
    try { await backend.killProcess(item.id); await refresh(); onToast('后台进程已停止'); }
    catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
  };
  return items.length ? <div className="grid gap-3">
    <button onClick={() => void refresh()} className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-fg-3 hover:text-fg"><RefreshCw size={13} />刷新</button>
    {items.map((item) => <article key={item.id} className="rounded-xl bg-sunken p-3 text-[12.5px]">
      <p className="m-0 break-all font-mono text-fg">{item.command}</p>
      <p className="mt-1 mb-0 text-fg-3">{item.status === 'running' ? '运行中' : `已结束${item.exit_code == null ? '' : `（退出码 ${item.exit_code}）`}`} · {item.id}</p>
      <div className="mt-2 flex gap-3"><button onClick={() => void readOutput(item.id)} className="text-brand hover:underline">查看输出</button>{item.status === 'running' && <button onClick={() => void stop(item)} className="inline-flex items-center gap-1 text-danger"><Square size={12} />停止</button>}</div>
      {outputs[item.id] && <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface p-2 text-[11.5px] text-fg-2">{outputs[item.id]}</pre>}
    </article>)}
  </div> : <Empty title="没有后台进程" body="运行中的命令及其最近结果会显示在这里。" />;
}
