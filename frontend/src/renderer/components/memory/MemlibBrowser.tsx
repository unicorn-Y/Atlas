import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { BookOpen, CalendarDays, Check, Database, FolderKanban, GitCompare, LoaderCircle, RefreshCw, Search, Sparkles, UserRound, X } from 'lucide-react';
import { api } from '../../services/api';
import { LibChangesView, PeopleView, TodayView } from './LibraryPages';
import { MOCK_MEMLIB_ENABLED, mockMemlib, mockStats, type Episode, type Entry, type MemlibItem, type OpenResult, type Project, type ProjectSummary, type Stats } from './mockMemlib';

type View = 'search' | 'timeline' | 'projects' | 'people' | 'me' | 'changes';
type Props = { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void };
export type FailedQueueItem = { id: number; created: string; session: string; stage: string; attempts: number; last_error: string };
type FailedQueueBusyId = number | 'all' | null;

export async function fetchFailedQueue(apiBaseUrl: string): Promise<FailedQueueItem[]> {
  const result = await api<{ items: FailedQueueItem[] }>(apiBaseUrl, '/api/memlib/queue/failed?limit=100');
  return result.items;
}

export async function retryFailedQueue(apiBaseUrl: string, id: number | null): Promise<{ retried: number }> {
  return api(apiBaseUrl, '/api/memlib/queue/retry', { method: 'POST', json: { id } });
}

export function FailedQueuePanel({ items, busyId, error, loading = false, onRetry, onRefresh }: {
  items: FailedQueueItem[];
  busyId: FailedQueueBusyId;
  error: string;
  loading?: boolean;
  onRetry: (id: number | null) => void;
  onRefresh: () => void;
}) {
  if (!items.length && !error && !loading) return null;
  return <section aria-label="失败队列" className="mx-4 mt-3 rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2 lg:mx-6">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-xs"><b>失败队列</b>{items.length > 0 && <span className="text-fg-3">{items.length} 条待恢复</span>}{loading && <LoaderCircle size={13} className="animate-spin text-fg-3" />}</div>
      <div className="flex items-center gap-1">
        <button type="button" className="btn ghost px-2 py-1 text-xs" disabled={loading || busyId !== null} onClick={onRefresh}><RefreshCw size={12} />刷新</button>
        {items.length > 0 && <button type="button" className="btn ghost px-2 py-1 text-xs" disabled={loading || busyId !== null} onClick={() => onRetry(null)}>{busyId === 'all' ? '正在重试…' : '全部重试'}</button>}
      </div>
    </div>
    {error && <p role="alert" className="mb-0 mt-2 text-xs text-danger">失败队列操作失败：{error}</p>}
    {items.length > 0 && <ul className="mb-0 mt-2 grid gap-1.5 p-0">
      {items.map((item) => <li key={item.id} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-t border-[var(--line)] pt-1.5 text-xs">
        <div className="min-w-0"><div className="flex flex-wrap gap-x-2 text-fg-3"><span>{item.session || '未知会话'}</span><span>{item.stage}</span><span>尝试 {item.attempts} 次</span><span>{asDate(item.created)}</span></div><p className="mb-0 mt-0.5 break-words text-danger">{item.last_error || '未提供错误详情'}</p></div>
        <button type="button" className="btn ghost px-2 py-1 text-xs" disabled={loading || busyId !== null} onClick={() => onRetry(item.id)} aria-label={`重试失败项 ${item.id}`}>{busyId === item.id ? '正在重试…' : '重试此项'}</button>
      </li>)}
    </ul>}
  </section>;
}

const SOURCES = [
  ['你说的', '你说的'], ['你改的', '你改的'], ['推测', '推测'], ['经历', '经历'], ['整理', '整理'], ['原对话', '原对话'],
] as const;
const RANGES = [['today', '今天'], ['7d', '7 天'], ['30d', '30 天'], ['all', '全部'], ['custom', '自定义']] as const;
const NAV: Array<{ id: View; title: string; icon: typeof Search }> = [
  { id: 'search', title: '搜索', icon: Search }, { id: 'timeline', title: '时间线', icon: CalendarDays },
  { id: 'projects', title: '项目', icon: FolderKanban }, { id: 'people', title: '人', icon: UserRound },
  { id: 'me', title: '关于你', icon: BookOpen }, { id: 'changes', title: '变动记录', icon: GitCompare },
];
const KIND_QUERY = 'memory,raw';
const today = () => new Date().toISOString().slice(0, 10);
const dateBefore = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
const sourceLabel = (source: string) => SOURCES.find(([key]) => key === source)?.[1] ?? (source || '来源不明');
const sourceTone = (source: string) => source === '你说的' ? 'bg-[var(--ok-soft)] text-[var(--ok)]' : source === '你改的' ? 'bg-[var(--brand-soft)] text-[var(--brand)]' : source === '推测' ? 'bg-[var(--danger-soft)] text-[var(--danger)]' : 'bg-[var(--sunken)] text-fg-2';
const asDate = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

function SourceTag({ source }: { source: string }) {
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] ${sourceTone(source)}`}>{sourceLabel(source)}</span>;
}

function Highlight({ text, query }: { text: string; query: string }) {
  const words = query.trim().split(/\s+/).filter(Boolean).slice(0, 8);
  if (!words.length) return <>{text}</>;
  const regex = new RegExp(`(${words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig');
  return <>{text.split(regex).map((part, index) => words.some((word) => word.toLocaleLowerCase() === part.toLocaleLowerCase())
    ? <mark key={`${index}-${part}`} className="rounded-sm bg-[var(--brand-soft)] px-0.5 text-inherit">{part}</mark> : part)}</>;
}

function MemoryActions({ entry, apiBaseUrl, onToast, onChanged }: { entry: Entry; apiBaseUrl: string; onToast: Props['onToast']; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(entry.text);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!text.trim() || text.trim() === entry.text) { setEditing(false); return; }
    setBusy(true);
    try { await api(apiBaseUrl, '/api/memlib/entry', { method: 'POST', json: { id: entry.id, text: text.trim() } }); onToast('已改好'); setEditing(false); onChanged(); }
    catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const forget = async () => {
    if (!window.confirm('不再把这条来源用于记忆？原始聊天记录仍可在原对话中手动查看。')) return;
    setBusy(true);
    try { await api(apiBaseUrl, '/api/memlib/forget', { method: 'POST', json: { id: entry.id } }); onToast('已忘掉'); onChanged(); }
    catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  return <div className="flex items-center gap-1">
    {editing ? <><input autoFocus value={text} onChange={(event) => setText(event.target.value)} className="min-w-0 rounded-md border border-[var(--line)] bg-[var(--panel)] px-2 py-1 text-sm" onKeyDown={(event) => { if (event.key === 'Enter') void save(); if (event.key === 'Escape') setEditing(false); }} /><button className="btn ghost" disabled={busy} aria-label="保存" onClick={() => void save()}><Check size={13} /></button></>
      : <><button className="btn ghost px-2 py-1 text-xs" disabled={busy} onClick={() => setEditing(true)}>改</button><button className="btn ghost px-2 py-1 text-xs" disabled={busy} onClick={() => void forget()}>忘掉</button></>}
  </div>;
}

function RefDrawer({ refId, apiBaseUrl, onClose, onToast }: { refId: string; apiBaseUrl: string; onClose: () => void; onToast: Props['onToast'] }) {
  const [data, setData] = useState<OpenResult | null>(null);
  const [error, setError] = useState('');
  const [windowSize, setWindowSize] = useState(1);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = MOCK_MEMLIB_ENABLED ? mockMemlib.open(refId) : await api<OpenResult>(apiBaseUrl, `/api/memlib/open?ref=${encodeURIComponent(refId)}&window=${windowSize}`);
        if (active) setData(result);
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : String(reason)); }
    };
    void load(); return () => { active = false; };
  }, [apiBaseUrl, refId, windowSize]);
  useEffect(() => { const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key); }, [onClose]);
  return <div className="fixed inset-0 z-[70]">
    <button type="button" aria-label="关闭出处" className="absolute inset-0 h-full w-full bg-black/35" onClick={onClose} />
    <aside role="dialog" aria-modal="true" aria-label="出处" className="absolute inset-y-0 right-0 flex w-full max-w-[560px] flex-col border-l border-[var(--line)] bg-[var(--panel)] shadow-2xl">
      <header className="border-b border-[var(--line)] p-4">
        <div className="flex items-center justify-between gap-3"><h2 className="m-0 text-base font-semibold">出处 · {data?.title ?? refId}</h2><button className="iconbtn" aria-label="关闭" onClick={onClose}><X size={16} /></button></div>
        {data && <><p className="mt-2 mb-2 break-all font-mono text-xs text-fg-3">{data.session} · 原对话</p>
          <button className="btn primary" onClick={() => { window.location.assign(`atlas://conversation/${encodeURIComponent(data.session)}`); onToast('正在打开对应对话'); }}>在对话里打开</button></>}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error && <p role="alert" className="text-sm text-danger">读取出处失败：{error}</p>}
        {!data && !error && <div className="flex items-center gap-2 text-sm text-fg-3"><LoaderCircle size={15} className="animate-spin" />正在读取原对话…</div>}
        {data?.truncated && <p className="text-xs text-fg-3">内容过长，当前显示部分原文。</p>}
        <div className="grid gap-3">{data?.messages.map((message, index) => message.tool
          ? <details key={`tool-${index}`} className="rounded-lg border border-[var(--line)] px-3 py-2 text-sm"><summary className="cursor-pointer"><b>{message.tool.ok === false ? '✗' : '✓'} {message.tool.name}</b><span className="ml-2 text-xs text-fg-3">{message.tool.args}</span></summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-fg-2">{message.tool.output}</pre></details>
          : <article key={`message-${index}`} className={`rounded-lg border border-[var(--line)] p-3 ${message.role === 'user' ? 'bg-[var(--sunk)]' : ''}`}><div className="mb-1 flex justify-between text-[11px] text-fg-3"><b>{message.role === 'user' ? '你' : 'Atlas'}</b><span>{asDate(message.at)}</span></div><p className="m-0 whitespace-pre-wrap text-sm">{message.text}</p></article>)}</div>
      </div>
      <footer className="border-t border-[var(--line)] p-3"><button className="btn ghost" disabled={windowSize > 1} onClick={() => setWindowSize(2)}>多看前后一轮</button></footer>
    </aside>
  </div>;
}

export default function MemlibBrowser({ apiBaseUrl, connected, onToast }: Props) {
  const [view, setView] = useState<View>('timeline');
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [sources, setSources] = useState<string[]>([]);
  const [range, setRange] = useState<(typeof RANGES)[number][0]>('all');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [stats, setStats] = useState<Stats | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [projectPath, setProjectPath] = useState('');
  const [projectRefresh, setProjectRefresh] = useState(0);
  const [items, setItems] = useState<MemlibItem[]>([]);
  const [total, setTotal] = useState(0);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [before, setBefore] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refId, setRefId] = useState('');
  const [failedQueue, setFailedQueue] = useState<FailedQueueItem[]>([]);
  const [failedQueueError, setFailedQueueError] = useState('');
  const [failedQueueLoading, setFailedQueueLoading] = useState(false);
  const [failedQueueBusyId, setFailedQueueBusyId] = useState<FailedQueueBusyId>(null);
  const requestId = useRef(0);
  const searchCount = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const loadFailedQueue = useCallback(async () => {
    if (!connected || MOCK_MEMLIB_ENABLED) {
      setFailedQueue([]);
      setFailedQueueLoading(false);
      setFailedQueueError('');
      return;
    }
    setFailedQueueLoading(true);
    setFailedQueueError('');
    try {
      setFailedQueue(await fetchFailedQueue(apiBaseUrl));
    } catch (reason) {
      setFailedQueueError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setFailedQueueLoading(false);
    }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void loadFailedQueue(); }, [loadFailedQueue]);
  const retryQueue = async (id: number | null) => {
    setFailedQueueBusyId(id ?? 'all');
    setFailedQueueError('');
    try {
      const result = await retryFailedQueue(apiBaseUrl, id);
      onToast(`已重新加入 ${result.retried} 条失败记录`);
      await loadFailedQueue();
    } catch (reason) {
      setFailedQueueError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setFailedQueueBusyId(null);
    }
  };
  const queryParams = useMemo(() => {
    const params = new URLSearchParams({ q: debouncedQuery, src: sources.join(','), kinds: KIND_QUERY, limit: '100', offset: '0' });
    const low = range === 'today' ? today() : range === '7d' ? dateBefore(7) : range === '30d' ? dateBefore(30) : range === 'custom' ? from : '';
    const high = range === 'custom' ? to : range === 'today' ? today() : '';
    if (low) params.set('from', low);
    if (high) params.set('to', high);
    if (projectFilter) params.set('project', projectFilter);
    return params;
  }, [debouncedQuery, sources, range, from, to, projectFilter]);

  useEffect(() => { const timer = window.setTimeout(() => setDebouncedQuery(query), 300); return () => window.clearTimeout(timer); }, [query]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); searchRef.current?.focus(); } };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, []);
  useEffect(() => { if (projectFilter) { const match = projects.find((item) => item.title === projectFilter); if (match) setProjectPath(match.path); } }, [projectFilter, projects]);
  useEffect(() => {
    if (MOCK_MEMLIB_ENABLED) { setStats(mockStats); return; }
    if (!connected) return;
    let active = true;
    void api<Stats>(apiBaseUrl, '/api/memlib/stats').then((value) => { if (active) setStats(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [apiBaseUrl, connected]);

  useEffect(() => {
    if (!connected && !MOCK_MEMLIB_ENABLED) return;
    let active = true;
    const load = async () => {
      try {
        const values = MOCK_MEMLIB_ENABLED ? mockMemlib.projects() : (await api<{ items: ProjectSummary[] }>(apiBaseUrl, '/api/memlib/projects')).items;
        if (!active) return;
        setProjects(values);
        const path = projectPath || values[0]?.path || '';
        if (path) setProjectPath(path);
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : String(reason)); }
    };
    void load(); return () => { active = false; };
  }, [apiBaseUrl, connected]);

  useEffect(() => {
    if (view !== 'projects' || !projectPath) return;
    let active = true;
    const load = async () => {
      try {
        const value = MOCK_MEMLIB_ENABLED ? mockMemlib.project(projectPath) : await api<Project>(apiBaseUrl, `/api/memlib/project?path=${encodeURIComponent(projectPath)}`);
        if (active) setProject(value);
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : String(reason)); }
    };
    void load(); return () => { active = false; };
  }, [apiBaseUrl, connected, projectPath, projectRefresh, view]);

  const loadSearch = useCallback(async (append = false) => {
    if (view !== 'search') return;
    const id = append ? requestId.current : ++requestId.current;
    const offset = append ? searchCount.current : 0;
    const params = new URLSearchParams(queryParams);
    params.set('offset', String(offset));
    if (!append) searchCount.current = 0;
    setLoading(true); setError('');
    try {
      const result = MOCK_MEMLIB_ENABLED ? mockMemlib.search(params) : await api<{ total: number; items: MemlibItem[] }>(apiBaseUrl, `/api/memlib/search?${params}`);
      if (id === requestId.current) { searchCount.current = offset + result.items.length; setItems((current) => append ? [...current, ...result.items] : result.items); setTotal(result.total); }
    } catch (reason) { if (id === requestId.current) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { if (id === requestId.current) setLoading(false); }
  }, [apiBaseUrl, queryParams, view]);
  useEffect(() => { void loadSearch(); }, [loadSearch]);

  const loadTimeline = useCallback(async (reset = false) => {
    if (view !== 'timeline' || loading || (!reset && !hasMore)) return;
    setLoading(true); setError('');
    try {
      const cursor = reset ? null : before;
      const result = MOCK_MEMLIB_ENABLED ? mockMemlib.timeline(cursor, 50) : await api<{ items: Episode[]; next: string | null }>(apiBaseUrl, `/api/memlib/timeline?limit=50${cursor ? `&before=${encodeURIComponent(cursor)}` : ''}${sources.length ? `&src=${encodeURIComponent(sources.join(','))}` : ''}`);
      setEpisodes((current) => reset ? result.items : [...current, ...result.items]);
      setBefore(result.next);
      setHasMore(Boolean(result.next) && result.items.length > 0);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, [apiBaseUrl, before, hasMore, loading, sources, view]);
  useEffect(() => { if (view === 'timeline') { setEpisodes([]); setBefore(null); setHasMore(true); void loadTimeline(true); } }, [view, sources]);

  const searchItems = items;
  const filteredEpisodes = useMemo(() => episodes.filter((item) => {
    if (projectFilter && item.text.toLocaleLowerCase().includes(projectFilter.toLocaleLowerCase()) === false && !item.outcome.toLocaleLowerCase().includes(projectFilter.toLocaleLowerCase())) return false;
    const day = item.day;
    if (range === 'today' && day !== today()) return false;
    if (range === '7d' && day < dateBefore(7)) return false;
    if (range === '30d' && day < dateBefore(30)) return false;
    if (range === 'custom' && ((from && day < from) || (to && day > to))) return false;
    return true;
  }), [episodes, from, projectFilter, range, to]);
  const timelineRows = useMemo(() => filteredEpisodes.flatMap((item, index) => {
    const previous = filteredEpisodes[index - 1];
    return previous?.day === item.day ? [item] : [{ id: `day-${item.day}`, dayHeader: item.day } as { id: string; dayHeader: string }, item];
  }), [filteredEpisodes]);
  const openDrawer = useCallback((ref: string) => setRefId(ref), []);
  const chooseView = (next: View) => { setView(next); setError(''); };
  const toggleSource = (key: string) => setSources((current) => current.includes(key) ? current.filter((value) => value !== key) : [...current, key]);
  const runDream = async () => {
    try {
      const result = MOCK_MEMLIB_ENABLED ? { ok: true, projects: ['Atlas 记忆库'], added: 3, changed: 2, error: null } : await api<{ ok: boolean; projects: string[]; added: number; changed: number; error: string | null }>(apiBaseUrl, '/api/memlib/dream', { method: 'POST' });
      if (!result.ok || result.error) throw new Error(result.error || '整理未完成');
      onToast(`整理完成：更新 ${result.changed} 处，新增 ${result.added} 条`);
      if (!MOCK_MEMLIB_ENABLED) void api<Stats>(apiBaseUrl, '/api/memlib/stats').then(setStats).catch(() => undefined);
    } catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason)); }
  };

  const renderSearch = () => <section aria-label="搜索结果" className="min-h-0">
    <div className="mb-3 flex items-baseline justify-between gap-2"><div><h2 className="m-0 text-lg font-semibold">{debouncedQuery ? `“${debouncedQuery}”` : '搜索全部记忆'}</h2><p className="mt-1 mb-0 text-xs text-fg-3">找到 {total.toLocaleString()} 条 · 按相关度排序</p></div>{loading && <LoaderCircle size={16} className="animate-spin text-fg-3" />}</div>
    {error && <p role="alert" className="text-sm text-danger">读取失败：{error}</p>}
    {searchItems.length ? <div className="overflow-hidden rounded-lg border border-[var(--line)]"><Virtuoso style={{ height: 'min(68vh, 720px)' }} data={searchItems} endReached={() => { if (searchCount.current < total && !loading) void loadSearch(true); }} itemContent={(_, item) => <article className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2 border-b border-[var(--line)] px-4 py-3 last:border-0">
      <div className="min-w-0 text-sm"><div><Highlight text={item.snippet || item.text} query={debouncedQuery} /></div>{item.title && <p className="mt-1 mb-0 text-xs text-fg-3"><Highlight text={item.title} query={debouncedQuery} /></p>}</div><span className="font-mono text-xs text-fg-3">{item.score.toFixed(2)}</span>
      <div className="col-span-2 flex flex-wrap items-center gap-2 text-xs text-fg-3"><SourceTag source={item.src} /><span>{item.path}</span><span>{asDate(item.at)}</span><span>{item.project}</span>{item.ref && <button className="text-[var(--brand)] underline" onClick={() => openDrawer(item.ref)}>出处</button>}<MemoryActions entry={{ id: item.id, text: item.text, src: item.src, at: item.at, ref: item.ref }} apiBaseUrl={apiBaseUrl} onToast={onToast} onChanged={() => void loadSearch()} /></div>
    </article>} />
    </div> : !loading && <div className="rounded-lg border border-[var(--line)] p-8 text-center text-sm text-fg-3">{error ? '搜索暂不可用。' : '没搜到。试试换个说法，或勾选「原对话」。'}</div>}
  </section>;

  const renderTimelineRow = (_index: number, row: (Episode | { id: string; dayHeader: string })) => {
    if ('dayHeader' in row) return <h3 className="sticky top-0 z-10 mb-2 mt-3 border-b border-[var(--line)] bg-[var(--bg)] py-2 text-sm font-medium text-fg-2">{row.dayHeader.slice(5).replace('-', ' 月 ')} 日 · {filteredEpisodes.filter((episode) => episode.day === row.dayHeader).length} 条</h3>;
    const episode = row;
    return <article className="mb-2 overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--panel)]">
      <button className="grid w-full grid-cols-[48px_minmax(0,1fr)_auto] items-start gap-3 px-3 py-3 text-left" aria-expanded={false} onClick={(event) => { const next = event.currentTarget.nextElementSibling; if (next) next.classList.toggle('hidden'); event.currentTarget.setAttribute('aria-expanded', String(event.currentTarget.getAttribute('aria-expanded') !== 'true')); }}>
        <time className="pt-0.5 font-mono text-xs text-fg-3">{new Date(episode.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time><span className="min-w-0"><b className="block truncate text-sm font-medium">{episode.text}</b><span className="mt-1 block text-xs text-fg-2">{episode.outcome}</span></span><span className={`rounded-full px-2 py-0.5 text-[11px] ${episode.verified ? 'bg-[var(--ok-soft)] text-[var(--ok)]' : 'bg-[var(--sunken)] text-fg-3'}`}>{episode.verified ? '已验证' : '未验证'}</span>
      </button>
      <div className="hidden border-t border-[var(--line)] px-4 py-3 text-sm"><div className="grid gap-2">{([['定下的决定', episode.decisions], ['改过的文件', episode.files], ['跑过的命令', episode.commands], ['关键数字', episode.facts], ['没做完', episode.open_items], ['步骤', episode.steps]] as [string, string[]][]).filter(([, values]) => values.length).map(([label, values]) => <div key={label} className="grid grid-cols-[90px_minmax(0,1fr)] gap-2"><b className="text-xs text-fg-3">{label}</b><ul className="m-0 list-inside list-disc p-0">{values.map((value, idx) => <li key={`${idx}-${value}`} className="break-words">{value}</li>)}</ul></div>)}</div><div className="mt-3 flex items-center gap-2"><button className="btn ghost" onClick={() => openDrawer(episode.ref)}>打开原对话</button><MemoryActions entry={{ id: episode.id, text: episode.outcome, src: '经历', at: episode.at, ref: episode.ref }} apiBaseUrl={apiBaseUrl} onToast={onToast} onChanged={() => void loadTimeline(true)} /></div></div>
    </article>;
  };
  const renderTimeline = () => <section aria-label="时间线"><div className="mb-3"><h2 className="m-0 text-lg font-semibold">时间线</h2><p className="mt-1 mb-0 text-xs text-fg-3">按天倒序 · 点开经历查看决定、文件、命令和未完成项</p></div>
    {error && <p role="alert" className="text-sm text-danger">读取失败：{error}</p>}
    {timelineRows.length ? <Virtuoso style={{ height: 'min(68vh, 720px)' }} data={timelineRows} itemContent={renderTimelineRow} endReached={() => { void loadTimeline(); }} components={{ Footer: () => <div className="py-4 text-center text-xs text-fg-3">{loading ? '正在加载更早的经历…' : hasMore ? '继续向下滚动加载' : '已到最早记录'}</div> }} />
      : <div className="rounded-lg border border-[var(--line)] p-8 text-center text-sm text-fg-3">{loading ? '正在读取时间线…' : '还没有经历记录'}</div>}</section>;

  const renderProjects = () => <section aria-label="项目" className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
    <div className="overflow-hidden rounded-lg border border-[var(--line)]" aria-label="项目列表">{projects.map((item) => <button key={item.path} className={`w-full border-b border-[var(--line)] px-3 py-3 text-left last:border-0 ${item.path === projectPath ? 'bg-[var(--brand-soft)]' : 'hover:bg-[var(--sunk)]'}`} aria-current={item.path === projectPath} onClick={() => setProjectPath(item.path)}><b className="block truncate text-sm">{item.title}</b><span className="mt-1 flex justify-between text-[11px] text-fg-3"><span>{item.count} 条 · {item.open_items} 件未完</span><span>{asDate(item.updated)}</span></span></button>)}</div>
    {project ? <article className="min-w-0 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4"><div className="mb-3 border-b border-[var(--line)] pb-3"><h2 className="m-0 text-lg font-semibold">{project.title}</h2><p className="mt-1 mb-0 text-xs text-fg-3">{project.path}</p></div>{(['现在状态', '定下的决定', '没做完', '来龙去脉'] as const).map((section) => <section key={section} className="mb-4"><h3 className="mb-2 text-sm font-semibold">{section}</h3>{project.sections[section]?.length ? <div className="grid gap-2">{project.sections[section].map((entry) => <div key={entry.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-t border-[var(--sunken)] pt-2 text-sm"><div>{entry.text}{entry.why && <small className="mt-1 block text-xs text-fg-3">{entry.why}</small>}<div className="mt-1 flex items-center gap-2 text-xs text-fg-3">{asDate(entry.at)}{entry.ref && <button className="text-[var(--brand)] underline" onClick={() => openDrawer(entry.ref!)}>出处</button>}</div></div><div className="flex flex-wrap items-start justify-end gap-1"><SourceTag source={entry.src} /><MemoryActions entry={entry} apiBaseUrl={apiBaseUrl} onToast={onToast} onChanged={() => setProjectRefresh((value) => value + 1)} /></div></div>)}</div> : <p className="text-sm text-fg-3">暂无</p>}</section>)}</article> : <div className="p-6 text-sm text-fg-3">选择一个项目</div>}
  </section>;

  const renderContent = () => view === 'search' ? renderSearch() : view === 'timeline' ? renderTimeline() : view === 'projects' ? renderProjects() : view === 'people'
    ? <PeopleView apiBaseUrl={apiBaseUrl} connected={connected || MOCK_MEMLIB_ENABLED} onToast={onToast} />
    : view === 'me' ? <TodayView apiBaseUrl={apiBaseUrl} connected={connected || MOCK_MEMLIB_ENABLED} onToast={onToast} />
      : <LibChangesView apiBaseUrl={apiBaseUrl} connected={connected || MOCK_MEMLIB_ENABLED} onToast={onToast} sourceFilter={sources} />;

  return <div className="memory-browser -mx-4 -mt-4 grid min-h-full grid-cols-1 border-t border-[var(--line)] lg:-mx-6 lg:-mt-6 lg:grid-cols-[220px_minmax(0,1fr)]">
    <aside className="flex min-h-0 flex-col border-b border-[var(--line)] bg-[var(--sunk)] p-3 lg:border-b-0 lg:border-r" aria-label="记忆分区">
      <div className="mb-3 flex items-center gap-2 px-2"><Database size={16} className="text-[var(--brand)]"/><b className="text-sm">记忆库</b></div>
      <nav className="flex gap-1 overflow-x-auto lg:flex-col">{NAV.map(({ id, title, icon: Icon }) => <button key={id} aria-current={view === id ? 'page' : undefined} className={`flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm ${view === id ? 'bg-[var(--brand-soft)] font-medium text-[var(--brand)]' : 'text-fg-2 hover:bg-[var(--panel)]'}`} onClick={() => chooseView(id)}><Icon size={15}/>{title}{id === 'timeline' && stats?.episodes ? <span className="ml-auto hidden text-xs text-fg-3 lg:block">{stats.episodes.toLocaleString()}</span> : null}</button>)}</nav>
      <div className="mt-auto hidden border-t border-[var(--line)] pt-3 text-xs lg:block"><div className="grid gap-2"><div className="flex justify-between"><span className="text-fg-3">全部记忆</span><b>{stats ? (stats.facts + stats.episodes).toLocaleString() : '—'} 条</b></div><div className="flex justify-between"><span className="text-fg-3">今天新增</span><b>{stats?.today_added ?? '—'}</b></div><div className="flex justify-between"><span className="text-fg-3">上次整理</span><b>{stats?.last_dream ? asDate(stats.last_dream) : '—'}</b></div><div className="flex justify-between"><span className="text-fg-3">向量索引</span><b>{stats?.embed === 'ready' ? '已就绪' : stats?.embed === 'building' ? '构建中' : stats?.embed === 'unavailable' ? '不可用' : '—'}</b></div></div><button className="btn ghost mt-3 w-full justify-center" disabled={!connected && !MOCK_MEMLIB_ENABLED} onClick={() => void runDream()}><Sparkles size={14}/>立即整理</button></div>
    </aside>
    <main className="flex min-w-0 flex-col">
      <div className="sticky top-0 z-20 border-b border-[var(--line)] bg-[var(--bg)] px-4 py-3 lg:px-6"><label className="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2"><Search size={16} className="shrink-0 text-fg-3"/><input ref={searchRef} type="search" aria-label="搜索全部记忆" placeholder="搜你说过的、它做过的、原对话……  比如：记忆库 为什么不用向量" value={query} onChange={(event) => { setQuery(event.target.value); if (event.target.value.trim()) setView('search'); else if (view === 'search') setView('timeline'); }} className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none"/><kbd className="hidden text-[10px] text-fg-3 sm:inline">Ctrl K</kbd></label>
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs"><span className="mr-1 text-fg-3">来源</span>{SOURCES.map(([key, label]) => <button key={key} className={`rounded-full border border-[var(--line)] px-2 py-1 ${sources.includes(key) ? 'bg-[var(--brand-soft)] text-[var(--brand)]' : 'text-fg-2'}`} aria-pressed={sources.includes(key)} onClick={() => { toggleSource(key); if (view === 'timeline') setView('search'); }}>{label}</button>)}<span className="mx-1 h-4 border-l border-[var(--line)]"/><span className="mr-1 text-fg-3">时间</span>{RANGES.map(([key, label]) => <button key={key} className={`rounded-full border border-[var(--line)] px-2 py-1 ${range === key ? 'bg-[var(--brand-soft)] text-[var(--brand)]' : 'text-fg-2'}`} aria-pressed={range === key} onClick={() => setRange(key)}>{label}</button>)}
          {range === 'custom' && <><input type="date" aria-label="开始日期" value={from} onChange={(event) => setFrom(event.target.value)} className="rounded border border-[var(--line)] bg-[var(--panel)] px-1.5 py-1"/><span>至</span><input type="date" aria-label="结束日期" value={to} onChange={(event) => setTo(event.target.value)} className="rounded border border-[var(--line)] bg-[var(--panel)] px-1.5 py-1"/></>}
          <select aria-label="项目筛选" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)} className="ml-auto max-w-40 rounded-full border border-[var(--line)] bg-[var(--panel)] px-2 py-1"><option value="">全部项目</option>{projects.map((item) => <option key={item.path} value={item.title}>{item.title}</option>)}</select>
        </div>
      </div>
      {!connected && !MOCK_MEMLIB_ENABLED && <div className="mx-4 mt-3 rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-xs text-fg-3">记忆服务未连接，连接后即可读取和管理记忆。</div>}
      <FailedQueuePanel items={failedQueue} busyId={failedQueueBusyId} error={failedQueueError} loading={failedQueueLoading} onRetry={(id) => void retryQueue(id)} onRefresh={() => void loadFailedQueue()} />
      {error && view !== 'search' && <div role="alert" className="mx-4 mt-3 flex items-center justify-between rounded-lg bg-[var(--danger-soft)] px-3 py-2 text-xs text-danger"><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}><X size={14}/></button></div>}
      <div className="min-h-0 flex-1 overflow-hidden px-4 py-4 lg:px-6">{renderContent()}</div>
    </main>
    {refId && <RefDrawer refId={refId} apiBaseUrl={apiBaseUrl} onClose={() => setRefId('')} onToast={onToast}/>}
  </div>;
}
