import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ChevronRight, Globe, LoaderCircle, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { addMarketSource, listMarketSources, removeMarketSource, SOURCE_KIND_LABEL, type MarketSourceKind, type MarketTap } from '../../services/skillsMarketApi';

const KIND_OPTIONS: Array<{ id: MarketSourceKind; needsUrl: boolean }> = [
  { id: 'official', needsUrl: false },
  { id: 'skillssh', needsUrl: false },
  { id: 'clawhub', needsUrl: false },
  { id: 'github', needsUrl: true },
  { id: 'custom', needsUrl: true },
];

/** 技能来源（taps）管理：折叠面板，列出/添加/删除来源，出错不阻塞其他标签页。 */
export default function SourcesManager({ apiBaseUrl, onTapsChange }: {
  apiBaseUrl: string;
  onTapsChange?: (taps: MarketTap[]) => void;
}) {
  const [taps, setTaps] = useState<MarketTap[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [armed, setArmed] = useState('');
  const [form, setForm] = useState<{ kind: MarketSourceKind; url: string; proxy: string }>({ kind: 'skillssh', url: '', proxy: '' });

  // onTapsChange 只用来回传最新列表，不作为重新加载的依据。
  const tapsRef = useRef(onTapsChange);
  tapsRef.current = onTapsChange;
  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const next = await listMarketSources(apiBaseUrl);
      setTaps(next);
      tapsRef.current?.(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '技能来源暂时读不到，添加技能不受影响。');
    } finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, [apiBaseUrl]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const needsUrl = KIND_OPTIONS.find((item) => item.id === form.kind)?.needsUrl;
    if (needsUrl && !form.url.trim()) { setError('这类来源需要填写地址，例如 GitHub 仓库或索引 URL。'); return; }
    setBusy(true);
    setError('');
    try {
      const next = await addMarketSource(apiBaseUrl, {
        kind: form.kind,
        ...(form.url.trim() ? { url: form.url.trim() } : {}),
        ...(form.proxy.trim() ? { proxy: form.proxy.trim() } : {}),
      });
      setTaps(next);
      tapsRef.current?.(next);
      setForm({ kind: 'skillssh', url: '', proxy: '' });
      setAdding(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '来源没有添加成功，请检查地址后重试。');
    } finally { setBusy(false); }
  };

  const remove = async (id: string) => {
    setBusy(true);
    setError('');
    try {
      const next = await removeMarketSource(apiBaseUrl, id);
      setTaps(next);
      tapsRef.current?.(next);
      setArmed('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '来源没有删除成功，请稍后再试。');
    } finally { setBusy(false); }
  };

  return <section aria-label="技能来源管理" className="card-surface rounded-xl">
    <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}
      className="flex w-full items-center gap-1.5 rounded-xl px-3.5 py-2.5 text-left text-[13px] text-fg-2 hover:text-fg">
      <ChevronRight size={14} className={open ? 'rotate-90 transition-transform' : 'transition-transform'} />
      <Globe size={14} />技能来源（{taps.length}）
      <span className="ml-auto text-[11.5px] text-fg-3">市场从这些来源搜索技能</span>
    </button>
    {open && <div className="border-t border-[var(--line)] p-3.5 pt-3">
      {loading && <p role="status" className="m-0 flex items-center gap-2 text-[12.5px] text-fg-3"><LoaderCircle size={14} className="spin" />正在读取来源…</p>}
      {error && <div role="alert" className="error-note"><span>{error}</span><button type="button" className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}
      <ul className="m-0 list-none p-0">
        {taps.map((tap) => <li key={tap.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-hover">
          <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11.5px] text-fg-2">{SOURCE_KIND_LABEL[tap.kind]}</span>
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2">{tap.id}{tap.url ? ` · ${tap.url}` : ''}{tap.proxy ? ` · 代理 ${tap.proxy}` : ''}</span>
          <button type="button" className={`btn ghost h-7 px-2 text-[12px] ${armed === tap.id ? 'text-danger' : 'opacity-60 hover:opacity-100'}`}
            disabled={busy} onClick={() => { if (armed === tap.id) void remove(tap.id); else setArmed(tap.id); }}>
            {armed === tap.id ? <><Trash2 size={13} />再点一次删除</> : <><Trash2 size={13} />删除</>}
          </button>
        </li>)}
        {!loading && !taps.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">还没有配置来源，默认只有官方市场。</li>}
      </ul>
      {adding ? <form className="form mt-3" onSubmit={(event) => void submit(event)}>
        <div className="two">
          <label>类型<select aria-label="来源类型" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as MarketSourceKind })}>
            {KIND_OPTIONS.map((item) => <option key={item.id} value={item.id}>{SOURCE_KIND_LABEL[item.id]}</option>)}
          </select></label>
          <label>地址（可选，GitHub/自定义需要）<input aria-label="来源地址" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} placeholder="https://…" /></label>
        </div>
        <label>代理（可选）<input aria-label="代理地址" value={form.proxy} onChange={(event) => setForm({ ...form, proxy: event.target.value })} placeholder="http://127.0.0.1:7890" /></label>
        <div className="foot">
          <button type="button" className="btn ghost" disabled={busy} onClick={() => setAdding(false)}>取消</button>
          <button type="submit" className="btn primary" disabled={busy}>{busy ? <LoaderCircle size={15} className="spin" /> : <Plus size={15} />}{busy ? '正在添加…' : '添加来源'}</button>
        </div>
      </form> : <div className="mt-3 flex gap-2">
        <button type="button" className="btn" disabled={busy} onClick={() => setAdding(true)}><Plus size={15} />添加来源</button>
        <button type="button" className="btn ghost" disabled={loading} onClick={() => void load()}><RefreshCw size={15} />刷新</button>
      </div>}
    </div>}
  </section>;
}
