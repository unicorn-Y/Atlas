/** User-level new-run limits; enforcement is in AtlasKernel.run. */
import { useEffect, useState, type FormEvent } from 'react';
import { Save } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

type RunLimits = {
  engine_max_turns: number;
  user_max_turns: number | null;
  effective_max_turns: number;
  max_turns_limit: number;
  user_max_cost_usd: string | null;
  cost_limit_supported: boolean;
  cost_limit_reason: string;
};

export default function RunLimitsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [limits, setLimits] = useState<RunLimits | null>(null);
  const [value, setValue] = useState('');
  const [costValue, setCostValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-60';

  const load = async () => {
    const result = await api<RunLimits>(apiBaseUrl, '/api/run-limits');
    setLimits(result);
    setValue(result.user_max_turns === null ? '' : String(result.user_max_turns));
    setCostValue(result.user_max_cost_usd ?? '');
  };
  useEffect(() => {
    void load().catch((error) => setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) }));
  }, [apiBaseUrl]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!limits) return;
    const trimmed = value.trim();
    const maxTurns = trimmed ? Number(trimmed) : null;
    if (maxTurns !== null && (!Number.isInteger(maxTurns) || maxTurns < 1 || maxTurns > limits.max_turns_limit)) {
      setMessage({ ok: false, text: `轮数必须是 1 到 ${limits.max_turns_limit} 之间的整数。` });
      return;
    }
    const trimmedCost = costValue.trim();
    const maxCost = trimmedCost ? Number(trimmedCost) : null;
    if (maxCost !== null && (!Number.isFinite(maxCost) || maxCost < 0.001 || maxCost > 100000 || !/^\d{1,6}(?:\.\d{1,4})?$/.test(trimmedCost))) {
      setMessage({ ok: false, text: '估算费用上限必须是 0.001 到 100000 之间、最多 4 位小数的金额。' });
      return;
    }
    setBusy(true);
    try {
      const updated = await api<RunLimits>(apiBaseUrl, '/api/run-limits', { method: 'PUT', json: { max_turns: maxTurns, max_cost_usd: maxCost } });
      setLimits(updated);
      setValue(updated.user_max_turns === null ? '' : String(updated.user_max_turns));
      setCostValue(updated.user_max_cost_usd ?? '');
      setMessage({ ok: true, text: `已保存。新运行的有效上限为 ${updated.effective_max_turns} 轮${updated.user_max_cost_usd ? `，估算费用上限为 $${updated.user_max_cost_usd}` : ''}。` });
    } catch (error) {
      setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  return <section className="grid gap-4 text-[12.5px] text-fg-2">
    <header className="grid gap-1">
      <h2 className="text-[15px] font-semibold text-fg">运行限制</h2>
      <p className="text-[12px] text-fg-3">设置用户级轮数上限。它作用于新运行，不会更改已经开始的运行。</p>
    </header>
    {limits ? <form onSubmit={(event) => void save(event)} className="grid max-w-2xl gap-4">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(220px,2fr)] items-end gap-3 rounded-xl border border-line p-4">
        <label className="grid gap-1">用户轮数上限
          <input type="number" min={1} max={limits.max_turns_limit} step={1} value={value} onChange={(event) => setValue(event.target.value)} placeholder={`使用引擎默认值 ${limits.engine_max_turns}`} className={field} />
        </label>
        <p className="pb-1 text-[12px] leading-relaxed text-fg-3">引擎上限：{limits.engine_max_turns} 轮。留空使用引擎默认值；填入更小数值会限制每次新运行的主循环轮数。</p>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(220px,2fr)] items-end gap-3 rounded-xl border border-line p-4">
        <label className="grid gap-1">单次运行估算费用上限（USD）
          <input type="number" min={0.001} max={100000} step={0.0001} value={costValue} onChange={(event) => setCostValue(event.target.value)} placeholder="不限制" className={field} />
        </label>
        <p className="pb-1 text-[12px] leading-relaxed text-fg-3">{limits.cost_limit_reason}留空则不启用估算费用上限。</p>
      </div>
      <div><Button type="submit" variant="primary" disabled={busy}><Save />{busy ? '保存中…' : '保存运行限制'}</Button></div>
    </form> : <p className="text-fg-3">正在读取引擎限制…</p>}
    {message && <p role="status" className={cn('whitespace-pre-wrap text-[12px]', message.ok ? 'text-brand' : 'text-danger')}>{message.text}</p>}
  </section>;
}
