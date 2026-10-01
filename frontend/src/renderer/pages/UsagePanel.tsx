import { useEffect, useMemo, useState } from 'react';
import type { UsageGroup, UsageReport, UsageRow } from '@atlas/backend-adapter';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import { cn } from '../ui/cn';

const RANGES: Array<[string, number | null]> = [['近 7 天', 7], ['近 30 天', 30], ['全部', null]];
const GROUPS: Array<[UsageGroup, string]> = [['day', '按天'], ['conversation', '按对话'], ['model', '按模型']];

const tokens = (value: number) => value >= 1_000_000 ? `${(value / 1_000_000).toFixed(1)}M` : value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}k` : String(value);
const percent = (value: number | null) => value === null ? '—' : `${Math.round(value * 100)}%`;
const cost = (value: number | null) => value === null ? '价格未知' : `≈ ${value < 0.01 && value > 0 ? '<0.01' : value.toFixed(2)}`;

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - days + 1);
  return date.toISOString().slice(0, 10);
}

/** Token usage and cost from the backend ledger: totals, a per-day bar chart, and the table behind it. */
export default function UsagePanel() {
  const conversations = useAtlasStore((state) => state.conversations);
  const [days, setDays] = useState<number | null>(7);
  const [group, setGroup] = useState<UsageGroup>('day');
  const [report, setReport] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    backend.getUsage(group, days ? isoDaysAgo(days) : undefined)
      .then((value) => { if (live) setReport(value); })
      .catch((exc: unknown) => { if (live) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { live = false; };
  }, [group, days]);

  const titles = useMemo(() => new Map(conversations.map((item) => [item.id, item.title])), [conversations]);
  const label = (row: UsageRow) => group === 'conversation' ? titles.get(row.key) ?? '已删除的对话' : group === 'model' ? row.key.replace(/^[a-z]+\//, '') : row.key.slice(5);
  const rows = report?.rows ?? [];
  const totals = report?.totals;
  const noUsage = totals !== undefined && totals.input_tokens + totals.output_tokens === 0;

  const pill = 'h-8 rounded-lg px-3 text-[12.5px] transition-colors';
  return <div className="grid max-w-[720px] gap-5 text-[13px] text-fg-2">
    <div className="flex flex-wrap items-center gap-3">
      <div role="radiogroup" aria-label="时间范围" className="flex gap-1 rounded-[10px] bg-sunken p-1">
        {RANGES.map(([text, value]) => <button key={text} role="radio" aria-checked={days === value} onClick={() => setDays(value)}
          className={cn(pill, days === value ? 'bg-selected text-fg' : 'text-fg-3 hover:text-fg')}>{text}</button>)}
      </div>
      <div role="radiogroup" aria-label="分组方式" className="flex gap-1 rounded-[10px] bg-sunken p-1">
        {GROUPS.map(([value, text]) => <button key={value} role="radio" aria-checked={group === value} onClick={() => setGroup(value)}
          className={cn(pill, group === value ? 'bg-selected text-fg' : 'text-fg-3 hover:text-fg')}>{text}</button>)}
      </div>
    </div>

    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-danger">没能读取用量：{error}</p>}

    {totals && <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Tile label="输入" value={tokens(totals.input_tokens)} />
      <Tile label="输出" value={tokens(totals.output_tokens)} />
      <Tile label="缓存命中" value={percent(totals.cache_hit_rate)} hint="输入里由模型服务缓存提供的比例，越高越省钱" />
      <Tile label="估算费用" value={cost(totals.est_cost)} hint="按模型设置里填的价格估算；有模型没填价格时显示「价格未知」" />
    </div>}

    {noUsage && <p className="m-0 rounded-xl card-surface px-4 py-3 text-fg-3">这段时间还没有用量记录。新的任务跑完后会出现在这里。</p>}

    {group === 'day' && rows.length > 0 && !noUsage && <DayBars rows={days ? fillDays(rows, days) : rows} label={label} />}

    {rows.length > 0 && !noUsage && <div className="overflow-hidden rounded-xl card-surface">
      <table className="w-full border-collapse text-[12.5px]">
        <thead><tr className="text-left text-fg-3">
          {[GROUPS.find(([value]) => value === group)?.[1].replace('按', '') ?? '', '任务', '输入', '输出', '缓存命中', '估算费用'].map((head, index) =>
            <th key={head} className={cn('px-3 py-2 font-medium', index > 0 && 'text-right')}>{head}</th>)}
        </tr></thead>
        <tbody>{rows.map((row) => <tr key={row.key} className="border-t border-line">
          <td className="max-w-[260px] truncate px-3 py-2 text-fg" title={row.key}>{label(row)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{row.runs}</td>
          <td className="px-3 py-2 text-right tabular-nums">{tokens(row.input_tokens)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{tokens(row.output_tokens)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{percent(row.cache_hit_rate)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{cost(row.est_cost)}</td>
        </tr>)}</tbody>
      </table>
    </div>}

    <p className="m-0 text-[12px] leading-[1.7] text-fg-3">缓存命中一直是 0？如果用的是第三方中转网关，它可能没有转回模型服务的缓存信息。换成模型官方接口通常能看到命中，重复内容也更便宜。</p>
  </div>;
}

/** Every day of the range, zero where nothing ran, so the axis reads as time. */
function fillDays(rows: UsageRow[], days: number): UsageRow[] {
  const byDay = new Map(rows.map((row) => [row.key, row]));
  const empty = { runs: 0, input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, cache_hit_rate: null, est_cost: 0 };
  return Array.from({ length: days }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (days - 1 - index));
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    return byDay.get(key) ?? { key, label: key, ...empty };
  });
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="rounded-xl card-surface px-4 py-3" title={hint}>
    <div className="text-[12px] text-fg-3">{label}</div>
    <div className="mt-1 text-[20px] font-semibold tabular-nums text-heading">{value}</div>
  </div>;
}

/** One series (tokens per day): brand-colour bars, no legend, a tooltip per bar; the table below is the full view. */
function DayBars({ rows, label }: { rows: UsageRow[]; label: (row: UsageRow) => string }) {
  const [hover, setHover] = useState<number | null>(null);
  const values = rows.map((row) => row.input_tokens + row.output_tokens);
  const max = Math.max(...values, 1);
  const height = 140;
  return <figure className="m-0 rounded-xl card-surface px-4 pt-3 pb-2">
    <figcaption className="mb-2 text-[12px] text-fg-3">每天的 token 用量（输入 + 输出）</figcaption>
    <div className="relative flex items-end gap-[2px] border-b border-line" style={{ height }} onMouseLeave={() => setHover(null)}>
      {rows.map((row, index) => {
        const barHeight = values[index] ? Math.max(2, (values[index] / max) * (height - 18)) : 0;
        return <div key={row.key} className="relative flex h-full min-w-0 flex-1 items-end justify-center" onMouseEnter={() => setHover(index)}
          aria-label={`${label(row)}：${tokens(values[index])}`}>
          <div className={cn('w-full max-w-[36px] rounded-t-[4px] transition-opacity', hover !== null && hover !== index && 'opacity-50')}
            style={{ height: barHeight, background: 'var(--brand)' }} />
          {hover === index && <div role="tooltip" className="pop pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[12px] text-fg">
            <b className="font-medium">{label(row)}</b>　{tokens(values[index])} tokens · 缓存 {percent(row.cache_hit_rate)}
          </div>}
        </div>;
      })}
    </div>
    <div className="mt-1 flex justify-between text-[11px] tabular-nums text-fg-3">
      <span>{label(rows[0])}</span>{rows.length > 1 && <span>{label(rows[rows.length - 1])}</span>}
    </div>
  </figure>;
}
