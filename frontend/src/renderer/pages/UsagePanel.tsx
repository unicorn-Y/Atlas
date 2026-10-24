import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { UsageGroup, UsageReport, UsageRow } from '@atlas/backend-adapter';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import { cn } from '../ui/cn';
import { api } from '../services/api';

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

interface UsagePanelProps {
  username?: string;
  onSaveUsername?: (username: string) => void;
  apiBaseUrl?: string;
  conversationId?: string | null;
  onOpenModels?: () => void;
}
interface ConversationStats {
  input_tokens: number; output_tokens: number; cached_input_tokens: number;
  cache_hit_rate: number | null; est_cost: number | null; duration_seconds: number | null;
}

function readLocalProfile(): { name: string; about: string } {
  try {
    const value = JSON.parse(localStorage.getItem('atlas.preference.profile-local') ?? '{}') as Record<string, unknown>;
    return { name: typeof value.name === 'string' ? value.name : '', about: typeof value.about === 'string' ? value.about : '' };
  } catch { return { name: '', about: '' }; }
}

/** Token usage and cost from the backend ledger: totals, a per-day bar chart, and the table behind it. */
export default function UsagePanel({ username, onSaveUsername, apiBaseUrl = '', conversationId, onOpenModels }: UsagePanelProps = {}) {
  const conversations = useAtlasStore((state) => state.conversations);
  const [savedProfile] = useState(readLocalProfile);
  const [displayName, setDisplayName] = useState(username ?? savedProfile.name ?? '');
  const [about, setAbout] = useState(savedProfile.about);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [days, setDays] = useState<number | null>(7);
  const [group, setGroup] = useState<UsageGroup>('day');
  const [report, setReport] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionStats, setSessionStats] = useState<ConversationStats | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    backend.getUsage(group, days ? isoDaysAgo(days) : undefined)
      .then((value) => { if (live) setReport(value); })
      .catch((exc: unknown) => { if (live) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { live = false; };
  }, [group, days]);

  useEffect(() => {
    let live = true;
    setSessionStats(null);
    if (!conversationId || !apiBaseUrl) return () => { live = false; };
    void api<ConversationStats>(apiBaseUrl, `/api/conversations/${encodeURIComponent(conversationId)}/stats`)
      .then((value) => { if (live) setSessionStats(value); })
      .catch(() => { if (live) setSessionStats(null); });
    return () => { live = false; };
  }, [apiBaseUrl, conversationId]);

  const [heat, setHeat] = useState<UsageReport | null>(null);

  // The activity heatmap always reads a fixed 12-week daily window, independent of the range pills above,
  // so the view stays comparable no matter which range/group the rest of the panel is showing.
  useEffect(() => {
    let live = true;
    backend.getUsage('day', isoDaysAgo(84))
      .then((value) => { if (live) setHeat(value); })
      .catch(() => { if (live) setHeat(null); });
    return () => { live = false; };
  }, []);

  const titles = useMemo(() => new Map(conversations.map((item) => [item.id, item.title])), [conversations]);
  const label = (row: UsageRow) => group === 'conversation' ? titles.get(row.key) ?? '已删除的对话' : group === 'model' ? row.key.replace(/^[a-z]+\//, '') : row.key.slice(5);
  const rows = report?.rows ?? [];
  const totals = report?.totals;
  const noUsage = totals !== undefined && totals.input_tokens + totals.output_tokens === 0;
  const averageTokens = totals && totals.runs > 0 ? Math.round((totals.input_tokens + totals.output_tokens) / totals.runs) : 0;

  useEffect(() => { if (username !== undefined) setDisplayName(username); }, [username]);

  const saveProfile = (event: FormEvent) => {
    event.preventDefault();
    const name = displayName.trim().slice(0, 48) || 'User';
    setDisplayName(name);
    onSaveUsername?.(name);
    try { localStorage.setItem('atlas.preference.profile-local', JSON.stringify({ name, about: about.trim().slice(0, 240) })); } catch { /* storage unavailable */ }
    setProfileMessage('已保存在本机');
  };

  const pill = 'h-8 rounded-lg px-3 text-[12.5px] transition-colors';
  return <div className="grid max-w-[720px] gap-5 text-[13px] text-fg-2">
    {conversationId && <section aria-label="本会话用量" className="rounded-xl card-surface p-4">
      <h4 className="m-0 text-[13.5px] font-medium text-heading">本会话</h4>
      {sessionStats ? <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Tile label="输入 Token" value={tokens(sessionStats.input_tokens)} />
        <Tile label="输出 Token" value={tokens(sessionStats.output_tokens)} />
        <Tile label="缓存命中" value={percent(sessionStats.cache_hit_rate)} />
        <Tile label="估算费用" value={cost(sessionStats.est_cost)} />
        <Tile label="耗时" value={sessionStats.duration_seconds === null ? '未知' : `${Math.floor(sessionStats.duration_seconds / 3600)}小时${Math.floor(sessionStats.duration_seconds % 3600 / 60)}分`} />
      </div> : <p className="mt-2 mb-0 text-[12px] text-fg-3">正在读取本会话用量…</p>}
      {sessionStats?.est_cost === null && <p className="mt-2 mb-0 text-[12px] text-fg-3">该模型未配置价格，可在设置里填写。 <button type="button" onClick={onOpenModels} className="text-brand underline">打开模型设置</button></p>}
    </section>}
    <form onSubmit={saveProfile} className="rounded-xl card-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div><h4 className="m-0 text-[13.5px] font-medium text-heading">本机资料</h4><p className="mt-1 mb-0 text-[12px] text-fg-3">用于这台电脑上的 Atlas 个性化显示，不是云账号或在线个人主页。</p></div>
        <span className="shrink-0 rounded-full bg-sunken px-2.5 py-1 text-[11px] text-fg-3">仅本机</span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_1.5fr_auto] sm:items-end">
        <label className="text-[12px] text-fg-3">显示名称<input aria-label="本机显示名称" value={displayName} maxLength={48} onChange={(event) => setDisplayName(event.target.value)} placeholder="User" className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg" /></label>
        <label className="text-[12px] text-fg-3">个人备注<textarea aria-label="本机个人备注" rows={1} value={about} maxLength={240} onChange={(event) => setAbout(event.target.value)} placeholder="可选，只保存在本机" className="mt-1 block min-h-9 w-full resize-y rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-fg" /></label>
        <button type="submit" className="h-9 rounded-lg bg-brand px-3 text-[12px] font-medium text-on-primary">保存</button>
      </div>
      {profileMessage && <p role="status" className="mt-2 mb-0 text-[11.5px] text-fg-3">{profileMessage}</p>}
    </form>

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

    {totals && <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <Tile label="当前范围任务轮次" value={String(totals.runs)} hint="按上方选择的时间范围统计" />
      <Tile label="每轮平均 Token" value={tokens(averageTokens)} hint="当前范围输入与输出 Token 总量除以任务轮次" />
      <Tile label="个人资料范围" value="本机" hint="资料保存在当前设备浏览器存储中" />
    </div>}

    {totals && <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Tile label="输入" value={tokens(totals.input_tokens)} />
      <Tile label="输出" value={tokens(totals.output_tokens)} />
      <Tile label="缓存命中" value={percent(totals.cache_hit_rate)} hint="输入里由模型服务缓存提供的比例，越高越省钱" />
      <Tile label="估算费用" value={cost(totals.est_cost)} hint="按模型设置里填的价格估算；有模型没填价格时显示「价格未知」" />
    </div>}
    {totals?.est_cost === null && <p className="m-0 rounded-xl card-surface px-4 py-3 text-[12px] text-fg-3">该模型未配置价格，可在模型设置里填写。 <button type="button" onClick={onOpenModels} className="text-brand underline">打开模型设置</button></p>}

    {noUsage && <p className="m-0 rounded-xl card-surface px-4 py-3 text-fg-3">这段时间还没有用量记录。新的任务跑完后会出现在这里。</p>}

    {group === 'day' && rows.length > 0 && !noUsage && <DayBars rows={days ? fillDays(rows, days) : rows} label={label} />}
    <ActivityHeatmap rows={heat?.rows ?? []} />

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
          <td className="px-3 py-2 text-right tabular-nums">{percent(row.cache_hit_rate)}
            {row.cache_miss_reason && <div className="mt-0.5 whitespace-normal text-left text-[11px] font-normal leading-[1.5] text-fg-3" title="最近一次请求的缓存未命中原因">{row.cache_miss_reason}</div>}
          </td>
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

/** Five discrete intensity levels mapped to --brand mixes; 0 tokens stays a flat empty cell. */
const HEAT_LEVELS = [
  'color-mix(in srgb, var(--brand) 14%, transparent)',
  'color-mix(in srgb, var(--brand) 32%, transparent)',
  'color-mix(in srgb, var(--brand) 54%, transparent)',
  'color-mix(in srgb, var(--brand) 76%, transparent)',
  'var(--brand)',
];

/** GitHub-style 12-week activity calendar. Columns are weeks (Mon→Sun); the last cell is today. */
function ActivityHeatmap({ rows }: { rows: UsageRow[] }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  const start = new Date(monday);
  start.setDate(monday.getDate() - 11 * 7);
  const end = new Date(monday);
  end.setDate(monday.getDate() + 6);

  const byDay = new Map(rows.map((row) => [row.key, row]));
  const days: Array<{ key: string; nice: string; date: Date; tokens: number; runs: number }> = [];
  for (let cursor = new Date(start); cursor <= end; cursor.setDate(cursor.getDate() + 1)) {
    const clone = new Date(cursor);
    const key = `${clone.getFullYear()}-${String(clone.getMonth() + 1).padStart(2, '0')}-${String(clone.getDate()).padStart(2, '0')}`;
    const row = byDay.get(key);
    days.push({ key, nice: key.slice(5), date: clone, tokens: row ? row.input_tokens + row.output_tokens : 0, runs: row?.runs ?? 0 });
  }
  const cycle = days.filter((day) => day.date <= today);
  const max = Math.max(...cycle.map((day) => day.tokens), 0);
  const level = (tokens: number) => (tokens <= 0 || max <= 0 ? 0 : Math.min(5, Math.ceil((tokens / max) * 5)));
  const activeDays = cycle.filter((day) => day.tokens > 0).length;

  return <figure className="m-0 rounded-xl card-surface px-4 pt-3 pb-2">
    <figcaption className="mb-3 flex flex-wrap items-baseline justify-between gap-2 text-[12px] text-fg-3">
      <span>近 12 周活动（每天输入 + 输出 token）</span>
      <span className="tabular-nums">活跃 {activeDays} 天</span>
    </figcaption>
    <div className="overflow-x-auto">
      <div className="grid grid-flow-col grid-rows-7 gap-[3px]" style={{ gridAutoColumns: '12px' }}>
        {days.map((day) => day.date > today
          ? <span key={day.key} className="size-3 rounded-[3px] opacity-0" aria-hidden />
          : <span key={day.key} role="img" aria-label={`${day.nice}：${tokens(day.tokens)} token，${day.runs} 轮`}
            title={`${day.nice} · ${tokens(day.tokens)} token · ${day.runs} 轮`}
            className="size-3 rounded-[3px] border border-line"
            style={{ background: level(day.tokens) ? HEAT_LEVELS[level(day.tokens) - 1] : undefined }} />)}
      </div>
    </div>
    <div className="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-fg-3">
      <span>少</span>{HEAT_LEVELS.map((color, index) => <span key={index} className="size-3 rounded-[3px] border border-line" style={{ background: color }} />)}<span>多</span>
    </div>
  </figure>;
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
