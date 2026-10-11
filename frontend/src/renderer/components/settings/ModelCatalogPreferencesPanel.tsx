import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Eye, EyeOff, Pin, PinOff, RefreshCw, Search } from 'lucide-react';
import { api } from '../../services/api';
import { cn } from '../../ui/cn';

type ModelCatalogEntry = {
  id: string;
  name: string;
  provider: string;
  category: string;
  hermes_provider: string;
  custom: boolean;
  selected: boolean;
  hidden: boolean;
  pinned: boolean;
};

export type ModelCatalogPreferences = {
  hidden_ids: string[];
  pinned_ids: string[];
  order_ids: string[];
};

type ModelCatalogPayload = {
  models: ModelCatalogEntry[];
  preferences: ModelCatalogPreferences;
  providers: string[];
  categories: string[];
};

const fieldClass = 'h-9 rounded-lg border border-line bg-surface px-2.5 text-[12px] text-fg';

export default function ModelCatalogPreferencesPanel({ apiBaseUrl, onPreferencesChange }: { apiBaseUrl: string; onPreferencesChange: (preferences: ModelCatalogPreferences) => void }) {
  const [catalog, setCatalog] = useState<ModelCatalogPayload | null>(null);
  const [query, setQuery] = useState('');
  const [provider, setProvider] = useState('');
  const [category, setCategory] = useState('');
  const [visibility, setVisibility] = useState<'all' | 'visible' | 'hidden'>('visible');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await api<ModelCatalogPayload>(apiBaseUrl, '/api/model-catalog/preferences');
      setCatalog(result);
      onPreferencesChange(result.preferences);
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, [apiBaseUrl, onPreferencesChange]);
  useEffect(() => { void load(); }, [load]);

  const visibleModels = useMemo(() => {
    if (!catalog) return [];
    const needle = query.trim().toLocaleLowerCase();
    return catalog.models.filter((model) => {
      if (provider && model.provider !== provider) return false;
      if (category && model.category !== category) return false;
      if (visibility === 'visible' && model.hidden) return false;
      if (visibility === 'hidden' && !model.hidden) return false;
      return !needle || [model.name, model.id, model.provider, model.hermes_provider, model.category]
        .some((value) => value.toLocaleLowerCase().includes(needle));
    });
  }, [catalog, category, provider, query, visibility]);

  const sortable = !query.trim() && !provider && !category && visibility === 'all';
  const save = async (preferences: ModelCatalogPreferences, noticeText: string) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<ModelCatalogPayload>(apiBaseUrl, '/api/model-catalog/preferences', {
        method: 'PUT', json: preferences,
      });
      setCatalog(result);
      onPreferencesChange(result.preferences);
      setNotice(noticeText);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };

  const toggleId = (field: 'hidden_ids' | 'pinned_ids', id: string, enabled: boolean, label: string) => {
    if (!catalog) return;
    const values = catalog.preferences[field].filter((value) => value !== id);
    if (enabled) values.push(id);
    const next = field === 'hidden_ids'
      ? { ...catalog.preferences, hidden_ids: values }
      : { ...catalog.preferences, pinned_ids: values };
    void save(next, `${label}偏好已保存。`);
  };

  const canMove = (id: string, delta: -1 | 1) => {
    if (!catalog || !sortable) return false;
    const model = catalog.models.find((row) => row.id === id);
    if (!model) return false;
    const group = catalog.models.filter((row) => row.pinned === model.pinned);
    const index = group.findIndex((model) => model.id === id);
    const neighbor = group[index + delta];
    return Boolean(neighbor);
  };

  const move = (id: string, delta: -1 | 1) => {
    if (!catalog || !canMove(id, delta)) return;
    const model = catalog.models.find((row) => row.id === id);
    if (!model) return;
    const group = catalog.models.filter((row) => row.pinned === model.pinned);
    const index = group.findIndex((row) => row.id === id);
    const neighbor = group[index + delta];
    if (!neighbor) return;
    const order = [...catalog.preferences.order_ids];
    const first = order.indexOf(id);
    const second = order.indexOf(neighbor.id);
    if (first < 0 || second < 0) return;
    [order[first], order[second]] = [order[second], order[first]];
    void save({ ...catalog.preferences, order_ids: order }, '模型显示顺序已保存。');
  };

  return <section className="grid gap-4" aria-label="模型目录偏好">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="m-0 text-[15px] font-semibold text-fg">模型目录偏好</h2>
        <p className="mt-1 mb-0 text-[12.5px] text-fg-3">仅管理 Atlas 当前模型目录中的模型。隐藏项从模型选择列表移除（每个选择器的当前值会保留）；置顶和顺序同步到模型列表。偏好不会更改模型配置或运行时目录。</p>
      </div>
      <button type="button" disabled={loading || busy} onClick={() => void load()} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12px] text-fg-2 hover:bg-hover disabled:opacity-50"><RefreshCw size={13} />刷新目录</button>
    </header>

    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{error}</p>}
    {notice && !error && <p role="status" className="m-0 text-[12px] text-fg-3">{notice}</p>}

    <div className="grid gap-2 sm:grid-cols-[minmax(190px,1fr)_auto_auto_auto]">
      <label className="relative">
        <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-fg-3" />
        <input type="search" aria-label="搜索模型目录" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、模型 ID 或服务商" className={`${fieldClass} w-full pl-8`} />
      </label>
      <select aria-label="按服务商筛选" value={provider} onChange={(event) => setProvider(event.target.value)} className={fieldClass}>
        <option value="">全部服务商</option>{catalog?.providers.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <select aria-label="按类别筛选" value={category} onChange={(event) => setCategory(event.target.value)} className={fieldClass}>
        <option value="">全部类别</option>{catalog?.categories.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <select aria-label="按显示状态筛选" value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)} className={fieldClass}>
        <option value="all">全部状态</option><option value="visible">仅显示</option><option value="hidden">仅隐藏</option>
      </select>
    </div>

    <p className="m-0 text-[11.5px] text-fg-3">{loading ? '正在读取当前模型目录…' : `${visibleModels.length}/${catalog?.models.length ?? 0} 个模型`}{!sortable && !loading ? ' · 清除搜索和筛选后可调整显示顺序' : ''}</p>
    <div className="grid gap-2" aria-label="模型目录条目" aria-busy={loading || busy}>
      {visibleModels.map((model) => <article key={model.id} className={cn('flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-3', model.hidden && 'opacity-75')}>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="truncate text-[12.5px] font-medium text-fg">{model.name}</strong>
            {model.selected && <span className="rounded-md bg-brand/10 px-1.5 py-0.5 text-[10px] text-brand">当前模型</span>}
            {model.custom && <span className="rounded-md bg-hover px-1.5 py-0.5 text-[10px] text-fg-3">自定义</span>}
            {model.hidden && <span className="rounded-md bg-hover px-1.5 py-0.5 text-[10px] text-fg-3">已隐藏</span>}
          </div>
          <p className="mt-0.5 mb-0 break-all font-mono text-[10.5px] text-fg-3">{model.id}</p>
          <p className="mt-0.5 mb-0 text-[10.5px] text-fg-3">{model.provider || '未分类服务商'}{model.category ? ` · ${model.category}` : ''}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label={`${model.pinned ? '取消置顶' : '置顶'} ${model.name}`} title={model.pinned ? '取消置顶' : '置顶'} disabled={loading || busy} onClick={() => toggleId('pinned_ids', model.id, !model.pinned, model.pinned ? '取消置顶' : '置顶')} className={cn('grid size-8 place-items-center rounded-lg border border-line hover:bg-hover disabled:opacity-50', model.pinned && 'text-brand')}>
            {model.pinned ? <PinOff size={14} /> : <Pin size={14} />}
          </button>
          <button type="button" aria-label={`${model.hidden ? '显示' : '隐藏'} ${model.name}`} title={model.hidden ? '显示' : '隐藏'} disabled={loading || busy} onClick={() => toggleId('hidden_ids', model.id, !model.hidden, model.hidden ? '显示' : '隐藏')} className="grid size-8 place-items-center rounded-lg border border-line text-fg-2 hover:bg-hover disabled:opacity-50">
            {model.hidden ? <Eye size={14} /> : <EyeOff size={14} />}
          </button>
          <button type="button" aria-label={`上移 ${model.name}`} title="上移" disabled={!canMove(model.id, -1) || loading || busy} onClick={() => move(model.id, -1)} className="grid size-8 place-items-center rounded-lg border border-line text-fg-2 hover:bg-hover disabled:opacity-40"><ChevronUp size={14} /></button>
          <button type="button" aria-label={`下移 ${model.name}`} title="下移" disabled={!canMove(model.id, 1) || loading || busy} onClick={() => move(model.id, 1)} className="grid size-8 place-items-center rounded-lg border border-line text-fg-2 hover:bg-hover disabled:opacity-40"><ChevronDown size={14} /></button>
        </div>
      </article>)}
      {!loading && !visibleModels.length && <p className="m-0 rounded-xl border border-dashed border-line p-6 text-center text-[12px] text-fg-3">{catalog?.models.length ? '没有匹配的模型，请调整筛选条件。' : '当前 Atlas 动态模型目录为空。'}</p>}
    </div>
  </section>;
}
