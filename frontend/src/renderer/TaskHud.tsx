import { useEffect, useState, type CSSProperties } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUpRight, Eye, EyeOff, Minus, X } from 'lucide-react';
import './task-hud.css';

type HudData = { state: 'running' | 'waiting' | 'idle'; summary: string };
function TaskHud() {
  const [data, setData] = useState<HudData>({ state: 'idle', summary: '空闲' });
  const [through, setThrough] = useState(false);
  useEffect(() => {
    const offData = window.atlasDesktop?.onTaskHudData?.(setData);
    const offClickThrough = window.atlasDesktop?.onTaskHudClickThroughState?.(setThrough);
    return () => { offData?.(); offClickThrough?.(); };
  }, []);
  const setClickThrough = (value: boolean) => { setThrough(value); window.atlasDesktop?.setTaskHudClickThrough?.(value); };
  return <main className="task-hud" aria-label="Atlas 系统任务悬浮状态窗">
    <div className="task-hud-card">
      <div className={`task-hud-indicator ${data.state}`} aria-label={data.state} />
      <div className="task-hud-info"><strong>Atlas · {data.state === 'running' ? '运行中' : data.state === 'waiting' ? '等待中' : '空闲'}</strong><span title={data.summary}>{data.summary}</span></div>
      <div className={`task-hud-wave ${data.state === 'running' ? 'active' : ''}`} aria-label="任务活动波形">{[1,2,3,4,5,6,7,8,9].map((bar) => <i key={bar} style={{ '--n': bar } as CSSProperties} />)}</div>
      <button title={through ? '关闭点击穿透' : '开启点击穿透'} aria-label={through ? '关闭点击穿透' : '开启点击穿透'} onClick={() => setClickThrough(!through)}>{through ? <EyeOff size={14}/> : <Eye size={14}/>}</button>
      <button title="返回对应任务" aria-label="返回对应任务" onClick={() => window.atlasDesktop?.taskHudReturn?.()}><ArrowUpRight size={14}/></button>
      <button title="隐藏" aria-label="隐藏任务悬浮窗" onClick={() => window.atlasDesktop?.hideTaskHud?.()}><Minus size={14}/></button>
      <button title="关闭" aria-label="关闭任务悬浮窗" onClick={() => window.atlasDesktop?.closeTaskHud?.()}><X size={14}/></button>
    </div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<TaskHud/>);
