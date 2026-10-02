import { useEffect, useState } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import { getComputerSteps, type ComputerStep } from '../../services/x2Api';

/** 电脑操控任务的步骤时间线（GET /api/computer/runs/{run_id}/steps）：截图缩略 + 动作说明。 */
export function ComputerStepList({ steps }: { steps: ComputerStep[] }) {
  if (!steps.length) return <p className="m-0 text-[13px] text-fg-3">这次任务还没有可回放的步骤。</p>;
  return <ol className="m-0 grid list-none gap-2 p-0">
    {steps.map((step, position) => {
      const index = step.index ?? position + 1;
      return <li key={`${index}-${step.timestamp ?? ''}`} className="flex items-start gap-3 rounded-xl card-surface px-3 py-2.5 text-[13px]">
        <span className="mt-px w-5 shrink-0 text-right text-[12px] tabular-nums text-fg-3">{index}</span>
        {step.thumbnail
          ? <img src={step.thumbnail} alt={`第 ${index} 步截图`} className="h-12 w-20 shrink-0 rounded-lg border border-line object-cover" loading="lazy" />
          : <span aria-hidden className="mt-1 size-2 shrink-0 rounded-full bg-brand" />}
        <span className="min-w-0 flex-1">
          <span className="text-fg">{step.action}</span>
          {step.target && <code className="ml-1.5 rounded-[5px] bg-code px-1.5 font-mono text-[12px] text-fg-2">{step.target}</code>}
          {step.timestamp && <small className="block text-[12px] text-fg-3">{new Date(step.timestamp).toLocaleString()}</small>}
        </span>
      </li>;
    })}
  </ol>;
}

/** 设置页 / 面板里回放一次电脑操控：按 runId 拉步骤，失败不阻塞（只显示中文提示）。 */
export default function ComputerReplayPanel({ apiBaseUrl, runId, className }: {
  apiBaseUrl: string;
  runId?: string;
  className?: string;
}) {
  const [steps, setSteps] = useState<ComputerStep[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    if (!runId) { setSteps([]); return; }
    let stale = false;
    setSteps(null);
    setLoading(true);
    getComputerSteps(apiBaseUrl, runId)
      .then((body) => { if (!stale) { setSteps(body.steps ?? []); setError(''); } })
      .catch((exc) => { if (!stale) { setSteps([]); setError(exc instanceof Error ? exc.message : String(exc)); } })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [apiBaseUrl, runId, reloadKey]);
  return <section aria-label="电脑操控回放" className={className}>
    <div className="flex items-center gap-2">
      <h3 className="m-0 text-[15px] font-semibold text-heading">电脑操控回放</h3>
      <span className="flex-1" />
      <button aria-label="重新加载步骤" disabled={!runId || loading} onClick={() => setReloadKey((value) => value + 1)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-40">
        {loading ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}刷新
      </button>
    </div>
    <p className="m-0 mt-1 mb-3 text-[13px] text-fg-3">Atlas 每动一步鼠标或键盘都会留下一张截图和一句说明，完成后可以在这里回看它做了什么。</p>
    {!runId ? <p className="m-0 text-[13px] text-fg-3">还没有选择要回放的电脑操控任务。</p>
      : steps === null ? <p className="m-0 text-[13px] text-fg-3">正在读取步骤…</p>
      : <>
        {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">读取步骤失败：{error}</p>}
        <ComputerStepList steps={steps} />
      </>}
  </section>;
}
