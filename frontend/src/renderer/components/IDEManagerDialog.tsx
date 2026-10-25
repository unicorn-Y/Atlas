import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';

type IDEState = { connected: boolean; name: string; version?: string; last_heartbeat?: string; workspace?: string | null; error?: string; lock_present?: boolean };
type Diagnostic = { file: string; severity: string; message: string; startLine: number; endLine: number };

export default function IDEManagerDialog({ open, onClose, apiBaseUrl, onToast, workspacePath, onOpenWorkspace }: {
  open: boolean; onClose: () => void; apiBaseUrl: string; onToast: (message: string) => void;
  workspacePath?: string;
  onOpenWorkspace?: () => void;
}) {
  const [state, setState] = useState<IDEState | null>(null);
  const [items, setItems] = useState<Diagnostic[]>([]);
  const [busy, setBusy] = useState('');
  const refresh = useCallback(async () => {
    const next = await api<IDEState>(apiBaseUrl, '/api/ide/status');
    setState(next);
  }, [apiBaseUrl]);
  useEffect(() => { if (open) void refresh().catch((error) => onToast(`读取 IDE 状态失败：${String(error)}`)); }, [open, refresh, onToast]);
  const action = async (name: 'reconnect' | 'configure' | 'diagnostics') => {
    setBusy(name);
    try {
      if (name === 'diagnostics') {
        const result = await api<{ items: Diagnostic[] }>(apiBaseUrl, '/api/ide/diagnostics', { method: 'POST' });
        setItems(result.items); onToast(`诊断完成：${result.items.length} 条警告或错误`);
      } else if (name === 'reconnect') {
        await api(apiBaseUrl, '/api/ide/reconnect', { method: 'POST' }); await refresh(); onToast('IDE 插件连接已刷新');
      } else { await api(apiBaseUrl, '/api/ide/configure', { method: 'POST' }); onToast('已打开 VS Code 插件设置'); }
    } catch (error) { onToast(`IDE 操作失败：${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(''); }
  };
  return <Dialog open={open} onOpenChange={(value) => { if (!value) onClose(); }} label="IDE 插件状态" className="flex max-h-[84vh] w-[min(760px,92vw)] flex-col bg-panel p-5 shadow-xl">
    <div className="flex items-center gap-3"><h2 className="m-0 text-[16px] font-semibold text-heading">IDE 插件状态</h2><span className="flex-1"/><Button variant="ghost" onClick={onClose}>关闭</Button></div>
    <div className="mt-4 rounded-xl border border-line bg-sunken p-4 text-[13px] text-fg">
      <p className="m-0 font-medium">{state?.connected ? '已连接 · VS Code' : '未连接 · VS Code'}</p>
      <dl className="mt-3 grid grid-cols-[130px_1fr] gap-x-3 gap-y-2 text-fg-2">
        <dt>插件版本</dt><dd className="m-0">{state?.version ?? '未知'}</dd>
        <dt>最后心跳</dt><dd className="m-0">{state?.last_heartbeat ? new Date(state.last_heartbeat).toLocaleString() : '暂无'}</dd>
        <dt>当前工作区</dt><dd className="m-0 break-all">{state?.workspace ?? '未提供'}</dd>
        <dt>连接诊断</dt><dd className="m-0">{state?.connected ? '本机桥接正常' : state?.error ?? '等待 VS Code 插件启动'}</dd>
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        {workspacePath && onOpenWorkspace && <Button variant="secondary" onClick={onOpenWorkspace}>打开会话工作目录</Button>}
        <Button variant="secondary" disabled={Boolean(busy)} onClick={() => void action('reconnect')}>{busy === 'reconnect' ? '正在连接…' : '重连'}</Button>
        <Button variant="secondary" disabled={Boolean(busy)} onClick={() => void action('configure')}>配置插件</Button>
        <Button variant="secondary" disabled={!state?.connected || Boolean(busy)} onClick={() => void action('diagnostics')}>{busy === 'diagnostics' ? '正在检查…' : '运行诊断'}</Button>
      </div>
    </div>
    {items.length > 0 && <div className="mt-4 min-h-0 overflow-auto rounded-xl border border-line p-3" aria-label="IDE 诊断结果"><h3 className="m-0 mb-2 text-[13px] font-semibold">诊断结果（{items.length}）</h3>{items.map((item, index) => <div key={`${item.file}:${item.startLine}:${index}`} className="border-t border-line py-2 text-[12px]"><p className="m-0 text-fg">{item.severity} · {item.message}</p><p className="m-0 break-all text-fg-3">{item.file}:{item.startLine}-{item.endLine}</p></div>)}</div>}
    {items.length === 0 && state?.connected && <p className="mt-3 text-[12px] text-fg-3">运行诊断后，警告和错误会显示在这里。</p>}
  </Dialog>;
}
