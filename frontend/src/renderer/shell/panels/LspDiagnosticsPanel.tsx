import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { api } from '../../services/api';
import { DiagnosticsList, SeverityDots } from '../../components/diagnostics';

type Item = { line: number; column: number; severity: 'error' | 'warning' | 'information' | 'hint'; code?: string; message: string };
type FileRow = { path: string; count: number; diagnostics: Item[] };
type Result = { available: boolean; count: number; files: FileRow[] };

export default function LspDiagnosticsPanel({ workspace }: { workspace: string }) {
  const apiBaseUrl = useAtlasStore((state) => state.apiBaseUrl);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let stale = false;
    setResult(null); setError('');
    api<Result>(apiBaseUrl, `/api/lsp/diagnostics?${new URLSearchParams({ workspace })}`)
      .then((value) => { if (!stale) setResult(value); })
      .catch((exc) => { if (!stale) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { stale = true; };
  }, [apiBaseUrl, workspace, refresh]);
  return <section aria-label="项目 LSP 诊断" className="grid gap-2">
    <div className="flex items-center gap-2"><h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg-2">项目诊断{result ? ` · ${result.count}` : ''}</h3>
      <button type="button" aria-label="刷新项目诊断" onClick={() => setRefresh((value) => value + 1)} className="rounded-md p-1 text-fg-3 hover:bg-hover hover:text-fg"><RefreshCw size={12} /></button></div>
    {error ? <p role="alert" className="m-0 text-[11px] text-danger">{error}</p>
      : !result ? <p className="m-0 text-[11px] text-fg-3">正在读取最新诊断…</p>
        : !result.available ? <p className="m-0 text-[11px] text-fg-3">语言服务当前未运行。</p>
          : !result.files.length ? <p className="m-0 text-[11px] text-fg-3">已跟踪文件没有诊断。</p>
            : <ul className="m-0 grid list-none gap-1.5 p-0">{result.files.map((file) => <li key={file.path} className="rounded-lg bg-sunken p-2">
              <div className="flex items-center gap-1.5"><code className="min-w-0 flex-1 truncate text-[10.5px] text-fg-2" title={file.path}>{file.path}</code><SeverityDots diagnostics={file.diagnostics} /><span className="text-[10px] text-fg-3">{file.count}</span></div>
              <DiagnosticsList diagnostics={file.diagnostics} />{file.count > file.diagnostics.length && <p className="m-0 text-[10px] text-fg-3">仅显示前 {file.diagnostics.length} 条</p>}
            </li>)}</ul>}
  </section>;
}
