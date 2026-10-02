import { useState } from 'react';
import { Check, CircleAlert, Globe } from 'lucide-react';
import { resolveBrowserHandoff, type BrowserHandoffResolution } from '../../services/x2Api';
import { Button } from '../../ui/Button';

const RESOLVED_TEXT: Record<BrowserHandoffResolution, string> = {
  open_panel: '已在浏览器面板打开，Atlas 在那里继续。',
  done: '收到，Atlas 继续执行。',
  give_up: '好的，这一步先跳过。',
};

/**
 * 浏览器代理卡住要交还给人时的交接卡（对应 browser.handoff_required 事件）：
 * 在浏览器面板打开 / 我弄好了，继续 / 做不了。选择 open_panel 时通过 onOpenPanel 通知宿主打开浏览器面板。
 */
export default function BrowserHandoffCard({ apiBaseUrl, runId, reason, url, onOpenPanel, onResolved }: {
  apiBaseUrl: string;
  runId: string;
  /** 后端给出的交接原因（事件里的 reason 字段）。 */
  reason: string;
  /** 卡住时正在访问的页面地址。 */
  url?: string;
  /** 选择「在浏览器面板打开」后由宿主打开浏览器面板（如设置 store 的面板 URL / 切换面板）。 */
  onOpenPanel?: () => void;
  onResolved?: (resolution: BrowserHandoffResolution) => void;
}) {
  const [resolution, setResolution] = useState<BrowserHandoffResolution | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const decide = (choice: BrowserHandoffResolution) => {
    if (busy || resolution !== null) return;
    setBusy(true);
    setError('');
    resolveBrowserHandoff(apiBaseUrl, runId, choice)
      .then(() => {
        setResolution(choice);
        if (choice === 'open_panel') onOpenPanel?.();
        onResolved?.(choice);
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  return <div className="overflow-hidden rounded-2xl card-surface">
    <div className="flex gap-3.5 border-l-[3px] border-brand px-4 py-3.5">
      <Globe size={18} className="mt-0.5 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14px] font-semibold text-heading">浏览器这一步需要你搭把手</p>
        <p className="mt-1 mb-0 text-[13px] text-fg-2">{reason}</p>
        {url && <p className="mt-1.5 mb-0 truncate text-[12.5px] text-fg-3">页面：<code className="rounded-[5px] bg-code px-1.5 font-mono text-[12px] text-fg-2" title={url}>{url}</code></p>}
        {resolution !== null
          ? <p className="mt-2.5 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2"><Check size={14} className="text-ok" />{RESOLVED_TEXT[resolution]}</p>
          : <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" disabled={busy} onClick={() => decide('open_panel')}>在浏览器面板打开</Button>
            <Button disabled={busy} onClick={() => decide('done')}>我弄好了，继续</Button>
            <Button variant="ghost" disabled={busy} onClick={() => decide('give_up')}>做不了</Button>
            {busy && <span className="self-center text-[12px] text-fg-3">正在发送…</span>}
          </div>}
        {error && <p role="alert" className="m-0 mt-2 flex items-center gap-1 text-[12.5px] text-danger"><CircleAlert size={13} className="shrink-0" />发送失败了：{error}。可以再试一次。</p>}
      </div>
    </div>
  </div>;
}
