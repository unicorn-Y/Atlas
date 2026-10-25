import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import { Empty } from './Empty';

interface RolloutArchive { run_id: string; exists: boolean; path: string | null; events: Array<Record<string, unknown>>; event_count?: number; size_bytes?: number; error?: string }

/** Read only view of Atlas's redacted per-run JSONL diagnostic archive. */
export default function RolloutPanel({ runId, apiBaseUrl }: { runId?: string; apiBaseUrl: string }) {
  const [archive, setArchive] = useState<RolloutArchive | null>(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!runId) { setArchive(null); return; }
    let stale = false;
    setArchive(null); setError('');
    api<RolloutArchive>(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/rollout`)
      .then((result) => { if (!stale) setArchive(result); })
      .catch((exc) => { if (!stale) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { stale = true; };
  }, [runId, apiBaseUrl, refresh]);
  if (!runId) return <Empty title="没有活动运行" body="开始一项任务后，这里会显示它的完整事件归档。" />;
  if (error) return <section role="alert" className="rounded-xl bg-danger-soft p-3 text-[12.5px] text-danger">读取运行归档失败：{error}<button type="button" onClick={() => setRefresh((value) => value + 1)} className="ml-2 underline">重试</button></section>;
  if (!archive) return <p role="status" className="py-6 text-center text-[13px] text-fg-3">正在读取运行事件归档…</p>;
  if (!archive.exists) return <Empty title="归档文件不存在" body={archive.error ?? '运行事件没有保存归档文件。'} />;
  return <section aria-label="运行事件归档" className="grid gap-3">
    <div className="rounded-xl card-surface p-3">
      <p className="m-0 mb-1 text-[12.5px] font-medium text-fg">本次运行完整事件流</p>
      <p className="m-0 break-all font-mono text-[11px] text-fg-3">{archive.path}</p>
      <p className="m-0 mt-1 text-[11.5px] text-fg-3">{archive.event_count ?? archive.events.length} 条事件 · {archive.size_bytes ?? 0} 字节 · 只读脱敏归档</p>
      <div className="mt-2 flex flex-wrap gap-2"><button type="button" onClick={() => { if (archive.path && window.atlasDesktop?.openPath) void window.atlasDesktop.openPath(archive.path).then((result) => setNotice(result === 'opened' || result === 'revealed' ? '已打开归档文件位置。' : `打开失败：${result}`)).catch((exc) => setNotice(exc instanceof Error ? exc.message : String(exc))); else setNotice('当前运行环境不支持打开本机文件。'); }} className="rounded-lg bg-brand-soft px-3 py-1.5 text-[12px] text-fg">打开归档路径</button><button type="button" onClick={() => void navigator.clipboard.writeText(archive.path ?? '').then(() => setNotice('已复制归档路径。')).catch(() => setNotice('剪贴板不可用，请手动复制上方路径。'))} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">复制路径</button><button type="button" onClick={() => { const blob = new Blob([archive.events.map((event) => JSON.stringify(event)).join('\n') + '\n'], { type: 'application/x-ndjson;charset=utf-8' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${archive.run_id}.jsonl`; anchor.click(); URL.revokeObjectURL(url); setNotice(`已导出 ${archive.event_count ?? archive.events.length} 条事件。`); }} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">导出事件 JSONL</button><button type="button" onClick={() => setRefresh((value) => value + 1)} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">重新读取</button></div>
      {notice && <p role="status" className="m-0 mt-2 text-[11.5px] text-fg-3">{notice}</p>}
    </div>
    <ol className="m-0 grid list-none gap-2 p-0">{archive.events.map((event, index) => <li key={`${String(event.timestamp ?? '')}-${index}`} className="overflow-hidden rounded-xl card-surface">
      <div className="flex flex-wrap gap-x-2 border-b border-line px-3 py-2 text-[11px] text-fg-3"><time>{String(event.timestamp ?? '无时间戳')}</time><b className="text-fg-2">{String(event.event ?? 'unknown')}</b><span className="font-mono">#{index + 1}</span></div>
      <pre className="m-0 max-h-60 overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-[1.5] text-fg-2">{JSON.stringify(event, null, 2)}</pre>
    </li>)}</ol>
  </section>;
}
