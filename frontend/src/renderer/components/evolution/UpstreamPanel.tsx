import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight, ChevronRight, CircleAlert, CircleCheck, ExternalLink, LoaderCircle, Lock, LockOpen,
  PackageCheck, RefreshCw, RotateCcw, Square, Zap,
} from 'lucide-react';
import {
  applyUpstream, cancelUpstreamRun, clearUpstreamFailure, getUpstream, holdUpstream, releaseUpstream,
  saveUpstreamSettings, startUpstreamCheck, type UpstreamCategory, type UpstreamComponent,
  type UpstreamMode, type UpstreamView,
} from '../../services/upstreamApi';

const errorText = (cause: unknown, fallback: string) => (cause instanceof Error ? cause.message : fallback);

const STATUS: Record<string, { label: string; tone: string }> = {
  latest: { label: '最新', tone: 'text-fg-3' },
  outdated: { label: '有新版', tone: 'text-brand' },
  held: { label: '已锁定', tone: 'text-fg-3' },
  unknown: { label: '查不到', tone: 'text-fg-3' },
  error: { label: '出错', tone: 'text-[var(--danger,#c2410c)]' },
};

const MODES: { value: UpstreamMode; label: string; hint: string }[] = [
  { value: 'auto', label: '自动追新', hint: '定时检查，有新版本就在预演副本里更新并验证，通过后提示重启' },
  { value: 'check', label: '只检查', hint: '定时检查并提示，更新要你点' },
  { value: 'off', label: '关闭', hint: '不自动做任何事' },
];

const RUN_STATE: Record<string, string> = {
  running: '正在追新', succeeded: '追新完成', partial: '部分完成', failed: '追新失败',
  nothing: '没有需要更新的', skipped: '已跳过', cancelled: '已取消', interrupted: '任务中断',
};

function ago(iso: string | null | undefined): string {
  if (!iso) return '从未';
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} 小时前` : `${Math.round(hours / 24)} 天前`;
}

/** 「组件追新」：Atlas 里所有第三方组件的版本清单，按类一键追到最新。 */
export default function UpstreamPanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast?: (message: string) => void }) {
  const [view, setView] = useState<UpstreamView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({});
  const [onlyOutdated, setOnlyOutdated] = useState(true);
  const [showSteps, setShowSteps] = useState(false);

  const load = useCallback(async () => {
    try {
      setView(await getUpstream(apiBaseUrl));
      setError('');
    } catch (cause) {
      setError(errorText(cause, '追新清单暂时读不到。'));
    }
  }, [apiBaseUrl]);

  const running = view?.run?.state === 'running';
  const active = running || Boolean(view?.checking);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), active ? 4000 : 60000);
    return () => window.clearInterval(timer);
  }, [load, active]);

  const act = async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    try {
      await fn();
      if (done) onToast?.(done);
    } catch (cause) {
      onToast?.(errorText(cause, '操作没有成功，请稍后再试。'));
    } finally {
      setBusy('');
      await load();
    }
  };

  const apply = (body: { ids?: string[]; category?: string }, label: string) => act(`apply:${label}`, async () => {
    const result = await applyUpstream(apiBaseUrl, body);
    const hot = Object.values(result.hot ?? {}).filter((row) => row.status === 'applied').length;
    if (result.started) onToast?.(`已开始在预演副本里${label}，你可以继续用 Atlas，完成后会提示重启`);
    else if (hot) onToast?.(`已即时更新 ${hot} 项`);
    else onToast?.(result.reason || '没有可以更新的项');
  });

  const restart = async () => {
    const started = await window.atlasDesktop?.applyUpdate?.().catch(() => false);
    if (!started) onToast?.('当前不是源码运行的桌面版，请手动重启 Atlas（会自动合并追新结果）。');
  };

  const byCategory = useMemo(() => {
    const groups = new Map<string, UpstreamComponent[]>();
    for (const item of view?.components ?? []) {
      groups.set(item.category, [...(groups.get(item.category) ?? []), item]);
    }
    return groups;
  }, [view]);

  if (!view) {
    return <section className="card-surface rounded-xl p-4 text-[13px] text-fg-3" aria-label="组件追新">
      {error ? <div role="alert" className="error-note"><span className="flex-1">{error}</span>
        <button className="btn ghost" onClick={() => void load()}>重试</button></div>
        : <span className="flex items-center gap-2"><LoaderCircle size={14} className="spin" />正在读取组件清单…</span>}
    </section>;
  }

  const { summary, settings, run } = view;
  const results = run?.results ?? {};
  const lastSteps = (run?.steps ?? []).slice(-1)[0];
  const pendingRestart = Boolean(view.pending) || Boolean(run?.restart_required && run.state !== 'running');

  return <section className="card-surface rounded-xl" aria-label="组件追新">
    <div className="flex flex-wrap items-start gap-3 px-4 pb-3 pt-3.5">
      <PackageCheck size={18} className="mt-0.5 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-medium text-fg">组件追新</div>
        <div className="mt-0.5 text-[12.5px] text-fg-3">
          Atlas 里共 {summary.total} 项别人的东西（内核、记忆、依赖包、MCP、借鉴代码…），
          <span className={summary.outdated ? 'text-brand' : ''}>{summary.outdated} 项有新版本</span>
          {summary.errors ? `，${summary.errors} 项查询出错` : ''}。上次检查 {ago(view.checked_at)}
          {view.checking && '（正在检查…）'}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="追新方式" className="flex rounded-lg bg-sunken p-0.5">
          {MODES.map((mode) => <button key={mode.value} role="radio" aria-checked={settings.mode === mode.value}
            title={mode.hint} disabled={Boolean(busy)}
            onClick={() => void act('mode', () => saveUpstreamSettings(apiBaseUrl, { mode: mode.value }), `已切换为「${mode.label}」`)}
            className={`rounded-md px-2.5 py-1 text-[12px] ${settings.mode === mode.value ? 'bg-[var(--surface,#fff)] text-fg shadow-sm' : 'text-fg-3 hover:text-fg'}`}>
            {mode.label}</button>)}
        </div>
        <button className="btn ghost" disabled={active || Boolean(busy)}
          onClick={() => void act('check', () => startUpstreamCheck(apiBaseUrl), '开始检查，可能要一两分钟')}>
          {view.checking ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}立即检查
        </button>
        <button className="btn primary" disabled={!view.supported || active || Boolean(busy) || !summary.actionable}
          title={view.supported ? '' : '安装包版本只能检查，从源码运行才能追新'}
          onClick={() => void apply({}, '把全部组件追到最新')}>
          {busy.startsWith('apply') ? <LoaderCircle size={15} className="spin" /> : <Zap size={15} />}
          一键追新{summary.actionable ? `（${summary.actionable}）` : ''}
        </button>
      </div>
    </div>

    {error && <div role="alert" className="error-note mx-4 mb-3"><span className="flex-1">{error}</span></div>}

    {run?.state && <div className="mx-4 mb-3 rounded-lg bg-sunken px-3 py-2.5 text-[12.5px]">
      <div className="flex items-center gap-2">
        {running ? <LoaderCircle size={14} className="spin text-brand" />
          : run.state === 'succeeded' ? <CircleCheck size={14} className="text-brand" /> : <CircleAlert size={14} className="text-fg-3" />}
        <span className="font-medium text-fg">{RUN_STATE[run.state] ?? run.state}</span>
        {running && run.phase && <span className="text-fg-3">· {run.phase}</span>}
        <span className="min-w-0 flex-1 truncate text-fg-3">{lastSteps?.text}</span>
        <button className="rounded-md px-1.5 py-0.5 text-fg-3 hover:bg-hover hover:text-fg" onClick={() => setShowSteps((value) => !value)}>
          {showSteps ? '收起' : '过程'}</button>
        {running && <button className="btn ghost" disabled={Boolean(busy)}
          onClick={() => void act('cancel', () => cancelUpstreamRun(apiBaseUrl), '已取消追新任务')}>
          <Square size={13} />取消</button>}
      </div>
      {showSteps && <ol className="mt-2 max-h-56 space-y-0.5 overflow-auto font-mono text-[11.5px] text-fg-2">
        {(run.steps ?? []).map((step, index) => <li key={index}>
          <span className="text-fg-3">{step.at.slice(11, 19)}</span> {step.text}</li>)}
        {run.error && <li className="whitespace-pre-wrap text-fg-3">{run.error}</li>}
      </ol>}
      {(run.warnings ?? []).map((warning) => <div key={warning} className="mt-1 text-fg-3">注意：{warning}</div>)}
    </div>}

    {pendingRestart && <div className="mx-4 mb-3 flex items-center gap-3 rounded-lg border border-[var(--line)] px-3 py-2.5 text-[12.5px]">
      <CircleCheck size={15} className="shrink-0 text-brand" />
      <span className="min-w-0 flex-1">
        新版本已在预演副本里验证通过（{(view.pending?.summary ?? run?.commits?.map((c) => c.group) ?? []).join('、')}）
        {view.pending?.pushed || run?.pushed ? '，并已推送到远端，另一台电脑点「更新」也能拿到' : ''}。重启 Atlas 后生效。
      </span>
      <button className="btn primary" onClick={() => void restart()}>立即重启更新</button>
    </div>}

    <div className="flex items-center gap-2 border-t border-[var(--line)] px-4 py-2 text-[12px] text-fg-3">
      <label className="flex items-center gap-1.5">
        <input type="checkbox" checked={onlyOutdated} onChange={(event) => setOnlyOutdated(event.target.checked)} />
        只看有新版本 / 出问题的
      </label>
      <span className="ml-auto">每 {settings.interval_hours} 小时检查一次{settings.push ? ' · 验证后推送到远端' : ''}</span>
    </div>

    <div className="border-t border-[var(--line)]">
      {summary.categories.map((category) => <CategoryRow key={category.id} category={category}
        items={byCategory.get(category.id) ?? []} open={Boolean(openCats[category.id])}
        onToggle={() => setOpenCats((value) => ({ ...value, [category.id]: !value[category.id] }))}
        onlyOutdated={onlyOutdated} results={results} busy={busy} disabled={!view.supported || active}
        onUpdateCategory={() => void apply({ category: category.id }, `更新「${category.label}」`)}
        onUpdate={(item) => void apply({ ids: [item.id] }, `更新 ${item.name}`)}
        onHold={(item) => void act(`hold:${item.id}`, () => holdUpstream(apiBaseUrl, item.id), `已锁定 ${item.name}，一键追新会跳过它`)}
        onRelease={(item) => void act(`hold:${item.id}`, () => releaseUpstream(apiBaseUrl, item.id), `已解锁 ${item.name}`)}
        onRetry={(item) => void act(`retry:${item.id}`, () => clearUpstreamFailure(apiBaseUrl, item.id), `${item.name} 下次会重新尝试`)}
      />)}
    </div>
  </section>;
}

function CategoryRow({ category, items, open, onToggle, onlyOutdated, results, busy, disabled, onUpdateCategory, onUpdate, onHold, onRelease, onRetry }: {
  category: UpstreamCategory;
  items: UpstreamComponent[];
  open: boolean;
  onToggle: () => void;
  onlyOutdated: boolean;
  results: Record<string, { status: string; note?: string; reason?: string }>;
  busy: string;
  disabled: boolean;
  onUpdateCategory: () => void;
  onUpdate: (item: UpstreamComponent) => void;
  onHold: (item: UpstreamComponent) => void;
  onRelease: (item: UpstreamComponent) => void;
  onRetry: (item: UpstreamComponent) => void;
}) {
  const rank = (item: UpstreamComponent) => ({ outdated: 0, error: 1, held: 2, unknown: 3 } as Record<string, number>)[item.status] ?? 4;
  const shown = items
    .filter((item) => !onlyOutdated || item.status !== 'latest' || results[item.id]?.status === 'failed')
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  return <div className="border-b border-[var(--line)] last:border-b-0">
    <div className="flex items-center gap-2 px-4 py-2">
      <button type="button" aria-expanded={open} onClick={onToggle}
        className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[13px] text-fg-2 hover:text-fg">
        <ChevronRight size={14} className={open ? 'rotate-90 transition-transform' : 'transition-transform'} />
        <span className="font-medium text-fg">{category.label}</span>
        <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11.5px] text-fg-2">{category.total}</span>
        {category.outdated > 0 && <span className="rounded-md bg-[color-mix(in_srgb,var(--brand)_14%,transparent)] px-1.5 py-0.5 text-[11.5px] text-brand">
          {category.outdated} 项有新版</span>}
        <span className="ml-2 hidden truncate text-[11.5px] text-fg-3 sm:inline">{category.hint}</span>
      </button>
      {category.actionable > 0 && <button className="btn ghost" disabled={disabled || Boolean(busy)} onClick={onUpdateCategory}>
        更新本类（{category.actionable}）</button>}
    </div>
    {open && <ul className="pb-2">
      {shown.length === 0 && <li className="px-10 py-1.5 text-[12.5px] text-fg-3">这一类都是最新的。</li>}
      {shown.map((item) => <ComponentRow key={item.id} item={item} result={results[item.id]} busy={busy} disabled={disabled}
        onUpdate={onUpdate} onHold={onHold} onRelease={onRelease} onRetry={onRetry} />)}
    </ul>}
  </div>;
}

function ComponentRow({ item, result, busy, disabled, onUpdate, onHold, onRelease, onRetry }: {
  item: UpstreamComponent;
  result?: { status: string; note?: string; reason?: string };
  busy: string;
  disabled: boolean;
  onUpdate: (item: UpstreamComponent) => void;
  onHold: (item: UpstreamComponent) => void;
  onRelease: (item: UpstreamComponent) => void;
  onRetry: (item: UpstreamComponent) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const status = STATUS[item.status] ?? STATUS.unknown;
  const failure = result?.status === 'failed' ? result.reason : item.last_failure?.reason;
  const packages = Array.isArray(item.detail?.packages) ? item.detail.packages as { name: string; current?: string; latest?: string }[] : [];
  const commits = Array.isArray(item.detail?.commits) ? item.detail.commits as { hash: string; subject: string }[] : [];
  const hasMore = Boolean(failure) || packages.length > 0 || commits.length > 0 || item.locations.length > 0;
  return <li className="px-4 py-1.5 pl-10 text-[12.5px]">
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <button type="button" className="min-w-0 max-w-[340px] truncate text-left font-medium text-fg hover:underline"
        title={item.id} onClick={() => hasMore && setExpanded((value) => !value)}>{item.name}</button>
      <span className="font-mono text-[11.5px] text-fg-3">{item.current || '—'}</span>
      {item.latest && item.latest !== item.current && <>
        <ArrowRight size={12} className="text-fg-3" />
        <span className="font-mono text-[11.5px] text-fg">{item.latest}</span>
      </>}
      <span className={`text-[11.5px] ${status.tone}`}>{status.label}</span>
      <span className="text-[11.5px] text-fg-3">· {item.strategy_label}</span>
      {result?.status === 'applied' && <span className="text-[11.5px] text-brand">· 已更新，待重启</span>}
      {failure && <span className="text-[11.5px] text-[var(--danger,#c2410c)]">· 上次没通过验证</span>}
      {item.note && <span className="min-w-0 truncate text-[11.5px] text-fg-3">· {item.note}</span>}
      <span className="ml-auto flex items-center gap-1">
        {item.url && <a href={item.url} target="_blank" rel="noreferrer" title="打开来源"
          className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ExternalLink size={13} /></a>}
        {failure && <button className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"
          title="忘掉失败记录，让自动追新重新尝试" disabled={Boolean(busy)} onClick={() => onRetry(item)}><RotateCcw size={13} /></button>}
        {item.held
          ? <button className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg" title={`已锁定：${item.hold_reason ?? ''}，点击解锁`}
            disabled={Boolean(busy)} onClick={() => onRelease(item)}><Lock size={13} /></button>
          : item.status !== 'latest' && <button className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"
            title="锁定当前版本（一键追新跳过它）" disabled={Boolean(busy)} onClick={() => onHold(item)}><LockOpen size={13} /></button>}
        {item.actionable && <button className="btn ghost !px-2 !py-0.5 text-[12px]" disabled={disabled || Boolean(busy)}
          onClick={() => onUpdate(item)}>更新</button>}
      </span>
    </div>
    {expanded && <div className="mt-1.5 space-y-1.5 rounded-lg bg-sunken px-3 py-2 text-[12px] text-fg-2">
      {failure && <div className="whitespace-pre-wrap break-words"><span className="text-fg-3">没通过的原因：</span>{failure}</div>}
      {commits.length > 0 && <div><div className="text-fg-3">上游最近的改动：</div>
        <ul className="mt-0.5 max-h-40 overflow-auto">{commits.map((commit) => <li key={commit.hash} className="truncate">
          <span className="font-mono text-fg-3">{commit.hash}</span> {commit.subject}</li>)}</ul></div>}
      {packages.length > 0 && <div><div className="text-fg-3">包括：</div>
        <div className="mt-0.5 max-h-40 overflow-auto font-mono text-[11.5px]">{packages.map((row) => <div key={row.name}>
          {row.name} {row.current} → {row.latest}</div>)}</div></div>}
      {item.locations.length > 0 && <div className="text-fg-3">位置：{item.locations.join('、')}</div>}
    </div>}
  </li>;
}
