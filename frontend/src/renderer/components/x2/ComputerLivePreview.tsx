import { useEffect, useState } from 'react';
import { Pause, Play, Monitor } from 'lucide-react';
import type { AgentEvent } from '../../../types/runtime';

/** Holds the last received frame while paused; resumed previews jump to the newest run frame. */
export default function ComputerLivePreview({ runId, events }: { runId: string; events: AgentEvent[] }) {
  const [paused, setPaused] = useState(false);
  const [frame, setFrame] = useState('');
  const latest = [...events].reverse().find((event) => event.type === 'computer.frame' && event.runId === runId)?.data.thumbnail;
  useEffect(() => { if (!paused && typeof latest === 'string') setFrame(latest); }, [latest, paused]);
  return <section className="mx-auto mt-2 w-[min(760px,100%)] overflow-hidden rounded-lg border border-line bg-sunken" aria-label="电脑操控实时画面">
    <div className="flex h-7 items-center gap-2 px-2 text-[11px] text-fg-3"><Monitor size={13} /><span className="flex-1">电脑操控 · 实时缩略画面</span><button type="button" aria-pressed={paused} onClick={() => setPaused((value) => !value)} className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-hover hover:text-fg">{paused ? <Play size={12} /> : <Pause size={12} />}{paused ? '继续刷新' : '暂停刷新'}</button></div>
    {frame ? <img src={frame} alt="最近一次电脑操控屏幕帧" className="block max-h-48 w-full bg-black object-contain" /> : <div className="grid h-24 place-items-center text-[11px] text-fg-3">等待 CUA 提供第一帧…</div>}
  </section>;
}
