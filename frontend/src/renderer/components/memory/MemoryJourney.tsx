import { useEffect, useState } from 'react';
import { api } from '../../services/api';

type JourneyItem = { id: string; kind: 'memory' | 'episode' | 'skill'; at: string; title: string; text: string; path: string; ref?: string; source: string };
type Props = { apiBaseUrl: string; connected: boolean; onOpenRef: (ref: string) => void; onToast: (text: string) => void };

export default function MemoryJourney({ apiBaseUrl, connected, onOpenRef, onToast }: Props) {
  const [items, setItems] = useState<JourneyItem[]>([]);
  const [before, setBefore] = useState('');
  const [kind, setKind] = useState('');
  const [query, setQuery] = useState('');
  const [source, setSource] = useState<{ id: string; path: string; text: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [hasMore, setHasMore] = useState(true);

  const load = async (reset = false) => {
    if (!connected || loading || (!reset && !hasMore)) return;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (!reset && before) params.set('before', before);
      if (kind) params.set('kind', kind);
      if (query.trim()) params.set('q', query.trim());
      const result = await api<{ items: JourneyItem[]; next: string | null }>(apiBaseUrl, `/api/memlib/journey?${params}`);
      setItems((current) => reset ? result.items : [...current, ...result.items]);
      setBefore(result.next || ''); setHasMore(Boolean(result.next));
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  };
  useEffect(() => { setItems([]); setBefore(''); setHasMore(true); void load(true); }, [apiBaseUrl, connected, kind, query]);
  useEffect(() => {
    const refresh = () => { setItems([]); setBefore(''); setHasMore(true); void load(true); };
    window.addEventListener('atlas:memories-updated', refresh);
    return () => window.removeEventListener('atlas:memories-updated', refresh);
  }, [apiBaseUrl, connected, kind, query]);

  const openSource = async (item: JourneyItem) => {
    if (item.ref) { onOpenRef(item.ref); return; }
    if (item.kind !== 'skill') { onToast(`记忆出处：${item.path}`); return; }
    try {
      const value = await api<{ path: string; text: string }>(apiBaseUrl, `/api/memlib/journey/source?id=${encodeURIComponent(item.id)}`);
      setSource({ id: item.id, path: value.path, text: value.text });
    } catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason)); }
  };

  return <section aria-label="学习与记忆 journey" className="min-h-0">
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3"><div><h2 className="m-0 text-lg font-semibold">学习与记忆 Journey</h2><p className="mt-1 mb-0 text-xs text-fg-3">按时间追踪形成的记忆、经历和经过验证的技能学习，可回到原对话或学习文件。</p></div>
      <div className="flex flex-wrap gap-2"><input aria-label="搜索 Journey" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索学习与记忆" className="h-8 rounded-md border border-[var(--line)] bg-[var(--panel)] px-2 text-sm"/><select aria-label="筛选 Journey 类型" value={kind} onChange={(event) => setKind(event.target.value)} className="h-8 rounded-md border border-[var(--line)] bg-[var(--panel)] px-2 text-sm"><option value="">全部类型</option><option value="memory">记忆</option><option value="episode">经历</option><option value="skill">技能学习</option></select></div>
    </div>
    {error && <p role="alert" className="text-sm text-danger">Journey 读取失败：{error}</p>}
    {!items.length && !loading && <div className="rounded-lg border border-[var(--line)] p-8 text-center text-sm text-fg-3">{error ? '暂时无法读取。' : '还没有学习或记忆事件。继续使用 Atlas 后，形成的记忆与采纳的技能会出现在这里。'}</div>}
    <div className="grid gap-2">{items.map((item) => <article key={item.id} className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><span className="rounded-full bg-[var(--brand-soft)] px-2 py-0.5 text-[11px] text-[var(--brand)]">{item.kind === 'skill' ? '技能学习' : item.kind === 'episode' ? '经历' : '记忆'}</span><b className="text-sm">{item.title}</b></div><time className="text-xs text-fg-3">{new Date(item.at).toLocaleString('zh-CN')}</time></div>
      <p className="mb-2 mt-2 whitespace-pre-wrap text-sm text-fg-2">{item.text}</p><div className="flex flex-wrap items-center gap-3 text-xs text-fg-3"><span>{item.source}</span><span className="font-mono">{item.path}</span><button className="text-[var(--brand)] underline" onClick={() => void openSource(item)}>{item.ref ? '打开原对话出处' : item.kind === 'skill' ? '打开学习文件' : '查看记忆出处'}</button></div>
      {source?.id === item.id && <div className="mt-3 border-t border-[var(--line)] pt-2"><div className="mb-1 flex justify-between text-xs"><b>{source.path}</b><button onClick={() => setSource(null)}>关闭</button></div><pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-fg-2">{source.text}</pre></div>}
    </article>)}</div>
    {items.length > 0 && <div className="py-4 text-center"><button className="btn ghost" disabled={loading || !hasMore} onClick={() => void load()}>{loading ? '正在读取…' : hasMore ? '加载更早事件' : '已到最早记录'}</button></div>}
  </section>;
}
