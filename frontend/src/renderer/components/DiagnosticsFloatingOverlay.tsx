import { useEffect, useState } from 'react';
import { api } from '../services/api';

export default function DiagnosticsFloatingOverlay({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<{ tasks: Array<{ id: string; kind: string; name: string; status: string; model?: string; duration_ms?: number; input_tokens?: number; output_tokens?: number; cached_tokens?: number }>; event_queue_length: number }>({ tasks: [], event_queue_length: 0 });
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'd') { event.preventDefault(); setOpen((value) => !value); } };
    const toggle = () => setOpen((value) => !value);
    window.addEventListener('keydown', key); window.addEventListener('atlas:toggle-debug-overlay', toggle);
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('atlas:toggle-debug-overlay', toggle); };
  }, []);
  useEffect(() => {
    if (!open) return;
    const refresh = () => void api<typeof state>(apiBaseUrl, '/api/diagnostics/tasks').then(setState).catch(() => undefined);
    refresh(); const timer = window.setInterval(refresh, 1000); return () => window.clearInterval(timer);
  }, [apiBaseUrl, open]);
  if (!open) return null;
  return <aside role="status" aria-label="实时调试浮层" className="fixed bottom-4 right-4 z-[120] w-[340px] rounded-xl border border-brand/40 bg-panel p-3 text-[11.5px] text-fg shadow-2xl">
    <div className="flex items-center justify-between"><strong>Atlas 实时调试</strong><button type="button" onClick={() => setOpen(false)} className="text-fg-3">关闭 · Ctrl+Shift+D</button></div>
    <div className="mt-2 grid gap-1 font-mono"><div>阶段：{state.tasks.some((task) => task.status === 'running') ? '运行中' : '空闲'}</div><div>活跃任务：{state.tasks.length}</div><div>事件队列：{state.event_queue_length}</div>{state.tasks.filter((task) => task.model).map((task) => <div key={task.id}>模型 {task.model} · {task.duration_ms ?? '未知'} ms · input/output {task.input_tokens ?? '未知'}/{task.output_tokens ?? '未知'} token · cache {task.cached_tokens ?? '未知'}</div>)}<div>工具调用耗时：运行时未单独提供此字段</div></div>
    <ul className="mb-0 mt-2 max-h-40 overflow-auto">{state.tasks.map((task) => <li key={task.id}>{task.kind} · {task.status} · {task.name}</li>)}</ul>
  </aside>;
}
