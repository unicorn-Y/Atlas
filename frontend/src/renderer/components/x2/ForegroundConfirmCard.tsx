import { useState } from 'react';
import { Check, MousePointerClick, ShieldAlert, X } from 'lucide-react';
import { resolveForeground } from '../../services/x2Api';
import { Button } from '../../ui/Button';

/**
 * 电脑操控需要在你正在用的前台窗口里动手时的确认卡（对应 computer.foreground_required 事件）。
 * 外观沿用审批卡（components/ConversationActivity.tsx 的 Approval）的壳：card-surface + 左侧色条。
 */
export default function ForegroundConfirmCard({ apiBaseUrl, runId, reason, target, onResolved }: {
  apiBaseUrl: string;
  runId: string;
  /** 后端给出的请求原因（事件里的 reason 字段）。 */
  reason: string;
  /** 将被操作的前台窗口 / 应用名，仅用于展示。 */
  target?: string;
  onResolved?: (approve: boolean) => void;
}) {
  const [outcome, setOutcome] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const decide = (approve: boolean) => {
    if (busy || outcome !== null) return;
    setBusy(true);
    setError('');
    resolveForeground(apiBaseUrl, runId, approve)
      .then(() => { setOutcome(approve); onResolved?.(approve); })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  return <div className="overflow-hidden rounded-xl card-surface">
    <div className="flex gap-3.5 border-l-[3px] border-danger px-4 py-3.5">
      <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14px] font-semibold text-heading">Atlas 想在你正在使用的窗口里操作</p>
        <p className="mt-1 mb-0 text-[13px] text-fg-2">{reason}</p>
        {target && <p className="mt-1.5 mb-0 truncate text-[12.5px] text-fg-3">前台窗口：<code className="rounded-[5px] bg-code px-1.5 font-mono text-[12px] text-fg-2">{target}</code></p>}
        {outcome !== null
          ? <p className="mt-2.5 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2">
            {outcome ? <><Check size={14} className="text-ok" />已批准前台操作</> : <><X size={14} className="text-danger" />已拒绝，Atlas 不会动你的前台窗口</>}
          </p>
          : <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" disabled={busy} onClick={() => decide(true)}><MousePointerClick size={14} />批准</Button>
            <Button disabled={busy} onClick={() => decide(false)}>拒绝</Button>
            {busy && <span className="self-center text-[12px] text-fg-3">正在发送…</span>}
          </div>}
        {error && <p role="alert" className="m-0 mt-2 text-[12.5px] text-danger">发送失败了：{error}。可以再试一次。</p>}
      </div>
    </div>
  </div>;
}
