import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { ChevronRight, CircleStop, MessageSquarePlus, Power, RotateCcw } from 'lucide-react';
import type { ProcessInfo } from '@atlas/backend-adapter';
import { backend } from '../../store/useAtlasStore';
import { relativeTime } from '../../services/api';
import { cn } from '../../ui/cn';

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/**
 * A PowerShell in the conversation's working directory, next to the processes Atlas started.
 * It stays mounted while other tabs are shown, so switching away hides it without ending the shell.
 */
export default function TerminalPanel({ cwd, active, command, onSendToAtlas }: {
  cwd: string; active: boolean;
  /** A command typed as `!cmd` in the composer; runs once the shell is ready. */
  command?: { id: string; text: string } | null;
  onSendToAtlas: (text: string) => void;
}) {
  const [session, setSession] = useState(0);
  const [closed, setClosed] = useState(false);
  const [selection, setSelection] = useState('');
  const termRef = useRef<Terminal | null>(null);
  const ranRef = useRef('');
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [notice, setNotice] = useState('');
  const hostRef = useRef<HTMLDivElement>(null);
  /** Refits the live terminal to its box; null while none is mounted. */
  const fitRef = useRef<(() => void) | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || closed) return;
    const term = new Terminal({
      fontFamily: '"Cascadia Mono", Consolas, "Microsoft YaHei Mono", monospace', fontSize: 12.5, cursorBlink: true, scrollback: 5000,
      // PowerShell's colours assume a dark background, so the terminal stays dark in every theme.
      theme: { background: '#1c1c1e', foreground: '#e4e4e7', cursor: cssVar('--brand') || '#c8a060', selectionBackground: '#ffffff33' },
    });
    // React may mount this twice in development; a disposed terminal must ignore late socket callbacks.
    let disposed = false;
    const safeFit = () => { if (!disposed && host.offsetWidth) { try { fit.fit(); } catch { /* not laid out yet */ } } };
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    termRef.current = term;
    const selected = term.onSelectionChange(() => setSelection(term.getSelection()));
    setStatus('connecting');
    setNotice('');
    const socket = new WebSocket(backend.terminalUrl(cwd));
    socketRef.current = socket;
    const sendSize = () => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows })); };
    socket.onopen = () => { if (disposed) return; setStatus('open'); safeFit(); sendSize(); term.focus(); };
    socket.onmessage = (message) => {
      if (disposed) return;
      let data: { type?: string; data?: string; code?: number; error?: string };
      try { data = JSON.parse(String(message.data)); } catch { return; }
      if (data.type === 'output' && data.data) term.write(data.data);
      else if (data.type === 'exit') { setStatus('closed'); setNotice(`终端已退出（代码 ${data.code ?? '?'}）`); }
      else if (data.type === 'error') setNotice(data.error === 'pywinpty is not installed' ? '后端缺少 pywinpty，终端不可用。在 core 环境里安装 pywinpty 后重启 Atlas。' : data.error ?? '终端出错了');
    };
    socket.onclose = () => { if (!disposed) setStatus('closed'); };
    const input = term.onData((data) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data })); });
    const resize = term.onResize(sendSize);
    const observer = new ResizeObserver(safeFit);
    observer.observe(host);
    fitRef.current = safeFit;
    return () => { disposed = true; observer.disconnect(); input.dispose(); resize.dispose(); selected.dispose(); socket.close(); term.dispose(); fitRef.current = null; termRef.current = null; setSelection(''); };
  }, [cwd, session, closed]);

  // Run a `!command` from the composer once, when the shell is connected.
  useEffect(() => {
    const socket = socketRef.current;
    if (!command || ranRef.current === command.id || status !== 'open' || socket?.readyState !== WebSocket.OPEN) return;
    ranRef.current = command.id;
    socket.send(JSON.stringify({ type: 'input', data: `${command.text}\r` }));
    termRef.current?.focus();
  }, [command, status]);
  // A new `!command` reopens a closed terminal; closing it again afterwards must stick.
  useEffect(() => { if (command && command.id !== ranRef.current) setClosed(false); }, [command]);

  useEffect(() => { if (active) fitRef.current?.(); }, [active]);

  return <div className="flex h-full min-h-0 flex-col gap-3">
    <div className="flex items-center gap-2 text-[12px] text-fg-3">
      <span className={cn('size-1.5 rounded-full', status === 'open' ? 'bg-ok' : status === 'connecting' ? 'bg-brand' : 'bg-fg-3')} />
      <span className="min-w-0 flex-1 truncate" title={cwd}>PowerShell · {cwd}</span>
      {selection.trim() && <button onClick={() => { onSendToAtlas(selection); termRef.current?.clearSelection(); }} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-fg-2 hover:bg-hover hover:text-fg"><MessageSquarePlus size={12} />发给 Atlas</button>}
      {!closed && <button onClick={() => setSession((value) => value + 1)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-hover hover:text-fg"><RotateCcw size={12} />{status === 'closed' ? '重新打开' : '重开'}</button>}
      <button onClick={() => { setClosed((value) => !value); setStatus('closed'); }} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-hover hover:text-fg"><Power size={12} />{closed ? '打开' : '关闭'}</button>
    </div>
    {notice && <p role="status" className="m-0 rounded-lg bg-sunken px-3 py-2 text-[12.5px] text-fg-2">{notice}</p>}
    {closed
      ? <p className="m-0 min-h-[220px] flex-1 rounded-xl bg-sunken p-4 text-[13px] text-fg-3">终端已关闭，PowerShell 进程已结束。点「打开」重新开一个。</p>
      : <div ref={hostRef} className="min-h-[220px] flex-1 overflow-hidden rounded-xl bg-[#1c1c1e] p-2" aria-label="终端" />}
    <Processes active={active} />
  </div>;
}

/** Background processes Atlas started, with their output and a way to stop them. */
function Processes({ active }: { active: boolean }) {
  const [items, setItems] = useState<ProcessInfo[]>([]);
  const [open, setOpen] = useState('');
  const [output, setOutput] = useState('');
  useEffect(() => {
    if (!active) return;
    let stale = false;
    const refresh = () => backend.getProcesses().then((list) => { if (!stale) setItems(list); }).catch(() => undefined);
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { stale = true; window.clearInterval(timer); };
  }, [active]);
  useEffect(() => {
    if (!open || !active) { setOutput(''); return; }
    let stale = false;
    let offset = 0;
    const poll = () => backend.getProcessOutput(open, offset).then((chunk) => {
      if (stale) return;
      offset = chunk.next;
      if (chunk.output) setOutput((current) => (current + chunk.output).slice(-20_000));
    }).catch(() => undefined);
    setOutput('');
    void poll();
    const timer = window.setInterval(poll, 1500);
    return () => { stale = true; window.clearInterval(timer); };
  }, [open, active]);

  if (!items.length) return null;
  return <section className="max-h-[40%] shrink-0 overflow-auto">
    <h3 className="m-0 mb-1.5 text-[12.5px] font-semibold text-fg-2">Atlas 启动的进程</h3>
    <div className="grid gap-1.5">{items.map((item) => <div key={item.id} className="overflow-hidden rounded-xl card-surface">
      <div className="flex items-center gap-2 px-3 py-2 text-[12.5px]">
        <button onClick={() => setOpen(open === item.id ? '' : item.id)} aria-expanded={open === item.id} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronRight size={12} className={cn('shrink-0 text-fg-3 transition-transform', open === item.id && 'rotate-90')} />
          <span className={cn('size-1.5 shrink-0 rounded-full', item.status === 'running' ? 'bg-ok' : 'bg-fg-3')} />
          <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg" title={item.command}>{item.command}</code>
        </button>
        <span className="shrink-0 text-[11.5px] text-fg-3">{item.status === 'running' ? relativeTime(item.started_at) : `已退出 ${item.exit_code ?? ''}`}</span>
        {item.status === 'running' && <button aria-label="停止这个进程" onClick={() => void backend.killProcess(item.id).then(() => setItems((list) => list.map((entry) => entry.id === item.id ? { ...entry, status: 'exited' } : entry)))}
          className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-danger"><CircleStop size={14} /></button>}
      </div>
      {open === item.id && <pre className="m-0 max-h-48 overflow-auto bg-code p-3 font-mono text-[11.5px] leading-[1.55] whitespace-pre-wrap text-fg-2 shadow-[inset_0_1px_0_var(--line)]">{output || '（还没有输出）'}</pre>}
    </div>)}</div>
  </section>;
}
