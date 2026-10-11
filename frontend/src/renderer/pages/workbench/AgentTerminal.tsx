import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { RotateCcw } from 'lucide-react';
import { cn } from '../../ui/cn';

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** 挂件的终端：它自己的命令行界面（终端模式），或同样隔离的 PowerShell（登录、装依赖用）。 */
export default function AgentTerminal({ url, label, active }: { url: string; label: string; active: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const fitRef = useRef<(() => void) | null>(null);
  const [round, setRound] = useState(0);
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const term = new Terminal({
      fontFamily: '"Cascadia Mono", Consolas, "Microsoft YaHei Mono", monospace', fontSize: 12.5, cursorBlink: true, scrollback: 8000,
      theme: { background: '#1c1c1e', foreground: '#e4e4e7', cursor: cssVar('--brand') || '#c8a060', selectionBackground: '#ffffff33' },
    });
    let disposed = false;
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    const safeFit = () => { if (!disposed && host.offsetWidth) { try { fit.fit(); } catch { /* not laid out yet */ } } };
    setStatus('connecting'); setNotice('');
    const socket = new WebSocket(url);
    const sendSize = () => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows })); };
    socket.onopen = () => { if (disposed) return; setStatus('open'); safeFit(); sendSize(); term.focus(); };
    socket.onmessage = (message) => {
      if (disposed) return;
      let data: { type?: string; data?: string; code?: number; error?: string };
      try { data = JSON.parse(String(message.data)); } catch { return; }
      if (data.type === 'output' && data.data) term.write(data.data);
      else if (data.type === 'exit') { setStatus('closed'); setNotice(`已退出（代码 ${data.code ?? '?'}）`); }
      else if (data.type === 'error') setNotice(data.error === 'pywinpty is not installed' ? '后端缺少 pywinpty，终端不可用。' : data.error ?? '终端出错了');
    };
    socket.onclose = () => { if (!disposed) setStatus('closed'); };
    const input = term.onData((data) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data })); });
    const resize = term.onResize(sendSize);
    const observer = new ResizeObserver(safeFit);
    observer.observe(host);
    fitRef.current = safeFit;
    return () => { disposed = true; observer.disconnect(); input.dispose(); resize.dispose(); socket.close(); term.dispose(); fitRef.current = null; };
  }, [url, round]);

  useEffect(() => { if (active) fitRef.current?.(); }, [active]);

  return <div className="flex h-full min-h-0 flex-col gap-2">
    <div className="flex items-center gap-2 text-[12px] text-fg-3">
      <span className={cn('size-1.5 rounded-full', status === 'open' ? 'bg-ok' : status === 'connecting' ? 'bg-brand' : 'bg-fg-3')} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <button onClick={() => setRound((value) => value + 1)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-hover hover:text-fg"><RotateCcw size={12} />{status === 'closed' ? '重新打开' : '重开'}</button>
    </div>
    {notice && <p role="status" className="m-0 rounded-lg bg-sunken px-3 py-2 text-[12.5px] text-fg-2">{notice}</p>}
    <div ref={hostRef} className="min-h-[260px] flex-1 overflow-hidden rounded-xl bg-[#1c1c1e] p-2" aria-label={label} />
  </div>;
}
