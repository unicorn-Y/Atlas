import { useEffect, useMemo, useState } from 'react';
import { api } from '../services/api';

interface ThinkbackMonth {
  month: number; label: string; future: boolean; has_records: boolean; outside_coverage: boolean;
  recorded_days: number; runs: number; input_tokens: number; output_tokens: number;
  est_cost: number | null; known_cost: number; unpriced_records: number;
}
interface ThinkbackReport {
  year: number; start_date: string; end_date: string; coverage_start: string | null; coverage_end: string | null;
  recorded_days: number; conversation_count: number; busiest_month: number | null; top_model: string | null;
  months: ThinkbackMonth[]; data_status: 'available' | 'empty';
  usage: { runs?: number; input_tokens?: number; output_tokens?: number; cached_input_tokens?: number; cache_hit_rate?: number | null; est_cost?: number | null; known_cost?: number; unpriced_records?: number };
}

const number = (value: number | undefined) => (value ?? 0).toLocaleString();
const token = (value: number | undefined) => (value ?? 0) >= 1_000_000 ? `${((value ?? 0) / 1_000_000).toFixed(1)}M` : (value ?? 0) >= 1000 ? `${((value ?? 0) / 1000).toFixed(1)}k` : number(value);
const money = (value: number | null | undefined) => value === null || value === undefined ? '未知' : `≈ $${value.toFixed(2)} USD`;

export default function ThinkbackPage({ apiBaseUrl }: { apiBaseUrl: string }) {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [report, setReport] = useState<ThinkbackReport | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [activeIndex, setActiveIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true); setError(''); setReport(null); setActiveIndex(0); setPlaying(false);
    void api<ThinkbackReport>(apiBaseUrl, `/api/u4/thinkback?year=${year}`)
      .then((value) => { if (live) { setReport(value); const fromEnd = [...value.months].reverse().findIndex((month) => month.has_records); setActiveIndex(fromEnd < 0 ? 0 : 11 - fromEnd); } })
      .catch((cause: unknown) => { if (live) setError(cause instanceof Error ? cause.message : String(cause)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [apiBaseUrl, year]);

  useEffect(() => {
    if (!playing || report?.data_status !== 'available') return;
    const timer = window.setInterval(() => setActiveIndex((index) => (index + 1) % 12), 1100);
    return () => window.clearInterval(timer);
  }, [playing, report?.data_status]);

  const months = report?.months ?? [];
  const activeMonth = months[activeIndex];
  const maxRuns = useMemo(() => Math.max(...months.map((month) => month.runs), 1), [months]);
  const usage = report?.usage;
  const setIndex = (index: number) => { setPlaying(false); setActiveIndex(Math.max(0, Math.min(11, index))); };
  const monthStatus = (month: ThinkbackMonth) => month.future ? '尚未到来' : month.has_records ? `${number(month.runs)} 轮 · ${number(month.recorded_days)} 个有记录日` : month.outside_coverage ? '超出账本覆盖范围' : '账本没有记录';

  return <section aria-label="年度使用回顾" className="mx-auto flex h-full w-full max-w-5xl min-h-0 flex-col overflow-auto px-7 py-6">
    <header className="mb-5 flex flex-wrap items-start gap-4 border-b border-line pb-4">
      <div className="min-w-0 flex-1"><h1 className="m-0 text-2xl font-semibold text-heading">年度使用回顾</h1><p className="mb-0 mt-1 text-[12px] text-fg-3">根据本机 Atlas 用量账本回看全年活动；缺失数据会明确标出，不补造趋势。</p></div>
      <label className="flex items-center gap-2 text-[12px] text-fg-2">年份<select aria-label="回顾年份" value={year} onChange={(event) => setYear(Number(event.target.value))} className="h-9 rounded-lg border border-line bg-surface px-2 text-fg">{Array.from({ length: currentYear - 1999 }, (_, index) => currentYear - index).map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    </header>

    {loading && <p role="status" className="rounded-lg bg-sunken p-3 text-sm text-fg-3">正在读取 {year} 年本机记录…</p>}
    {error && <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">没能读取年度记录：{error}</p>}
    {report && <>
      <p className="mb-4 rounded-lg bg-sunken px-3 py-2 text-[11.5px] text-fg-3">查询区间：{report.start_date} 至 {report.end_date}（UTC）。账本首末记录：{report.coverage_start && report.coverage_end ? `${report.coverage_start} 至 ${report.coverage_end}` : '无记录'}；有记录日：{number(report.recorded_days)} 天。此范围描述账本现有数据覆盖，区间以外及空白月份不代表没有发生使用。</p>
      {report.data_status === 'empty' && <p role="status" className="mb-4 rounded-xl border border-line p-4 text-sm text-fg-2">{year} 年没有可回顾的本机用量记录。这里不会生成虚构的调用次数、费用或趋势。</p>}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="模型调用" value={report.data_status === 'empty' ? '无记录' : number(usage?.runs)} />
        <Metric label="对话数" value={report.data_status === 'empty' ? '无记录' : number(report.conversation_count)} />
        <Metric label="输入 Token" value={report.data_status === 'empty' ? '无记录' : token(usage?.input_tokens)} />
        <Metric label="输出 Token" value={report.data_status === 'empty' ? '无记录' : token(usage?.output_tokens)} />
        <Metric label="估算费用" value={report.data_status === 'empty' ? '无记录' : money(usage?.est_cost)} detail={usage?.unpriced_records ? `${number(usage.unpriced_records)} 条记录缺价格` : undefined} />
        <Metric label="常用模型" value={report.data_status === 'empty' ? '无记录' : report.top_model || '未知'} />
      </div>
      {usage?.est_cost === null && usage.unpriced_records ? <p className="mb-4 mt-0 text-[11.5px] text-fg-3">显示已知价格部分 ≈ ${Number(usage.known_cost ?? 0).toFixed(4)} USD；其余 {number(usage.unpriced_records)} 条调用没有可用价格，因此全年总费用未知。</p> : null}

      <section aria-label="年度时间线" className="rounded-xl border border-line bg-surface p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2"><h2 className="m-0 text-[14px] font-medium text-heading">{year} 月度时间线</h2><span className="flex-1" />
          <button type="button" aria-label="上一个月" disabled={activeIndex === 0} onClick={() => setIndex(activeIndex - 1)} className="rounded-md border border-line px-2 py-1 text-xs text-fg-2 disabled:opacity-40">上一月</button>
          <button type="button" aria-label={playing ? '暂停回顾播放' : '播放年度回顾'} disabled={report.data_status === 'empty'} onClick={() => setPlaying((value) => !value)} className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-on-primary disabled:opacity-40">{playing ? '暂停' : '播放回顾'}</button>
          <button type="button" aria-label="下一个月" disabled={activeIndex === 11} onClick={() => setIndex(activeIndex + 1)} className="rounded-md border border-line px-2 py-1 text-xs text-fg-2 disabled:opacity-40">下一月</button>
        </div>
        <div role="group" aria-label="选择回顾月份" className="grid grid-cols-4 gap-2 sm:grid-cols-6 lg:grid-cols-12">
          {months.map((month, index) => <button key={month.month} type="button" aria-pressed={activeIndex === index} aria-label={`${year} 年 ${month.label}：${monthStatus(month)}`} onClick={() => setIndex(index)} className={`flex min-h-20 flex-col justify-end rounded-lg border px-1.5 pb-2 pt-1 text-center transition-colors ${activeIndex === index ? 'border-brand bg-brand/10 text-fg' : 'border-line text-fg-3 hover:bg-hover'}`}>
            <span className="mb-1 text-[10.5px]">{month.label.replace(' 月', '')}</span>
            <span className="mx-auto mb-1 w-2/3 rounded-t bg-brand/70" style={{ height: month.has_records ? `${Math.max(4, (month.runs / maxRuns) * 40)}px` : '2px', opacity: month.has_records ? 1 : 0.2 }} />
            <span className="truncate text-[9px]">{month.future ? '—' : month.has_records ? `${month.runs} 轮` : '无记录'}</span>
          </button>)}
        </div>
        <label className="sr-only" htmlFor="thinkback-month">选择月份</label><input id="thinkback-month" aria-label="时间线月份" type="range" min={0} max={11} value={activeIndex} onChange={(event) => setIndex(Number(event.target.value))} className="mt-4 w-full accent-[var(--brand)]" />
        {activeMonth && <article aria-live={playing ? 'polite' : 'off'} className="mt-3 rounded-lg bg-sunken p-4">
          <h3 className="m-0 text-[14px] font-medium text-heading">{year} 年 {activeMonth.label}</h3>
          <p className="mb-0 mt-1 text-[12px] text-fg-3">{monthStatus(activeMonth)}{report.busiest_month === activeMonth.month ? ' · 全年最活跃月份' : ''}</p>
          {activeMonth.has_records && <div className="mt-3 grid grid-cols-2 gap-2 text-[12px] sm:grid-cols-4"><span>输入：{token(activeMonth.input_tokens)} tokens</span><span>输出：{token(activeMonth.output_tokens)} tokens</span><span>估算费用：{money(activeMonth.est_cost)}</span><span>有记录日：{number(activeMonth.recorded_days)} 天</span></div>}
          {activeMonth.unpriced_records > 0 && <p className="mb-0 mt-2 text-[11px] text-fg-3">{number(activeMonth.unpriced_records)} 条记录缺价格；已知部分约 ${activeMonth.known_cost.toFixed(4)} USD。</p>}
        </article>}
      </section>
      <p className="mb-0 mt-4 text-[11px] leading-relaxed text-fg-3">费用按调用时可用的本地模型价格估算；缓存、Token 和费用只覆盖有本机账本记录的调用。删除的对话或账本尚未建立的历史活动不会被推测补全。</p>
    </>}
  </section>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="min-w-0 rounded-xl border border-line bg-surface px-3 py-3"><div className="text-[11px] text-fg-3">{label}</div><div className="mt-1 truncate text-[17px] font-semibold tabular-nums text-heading" title={value}>{value}</div>{detail && <div className="mt-1 text-[10px] text-fg-3">{detail}</div>}</div>;
}
