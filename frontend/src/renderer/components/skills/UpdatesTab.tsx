import { useCallback, useEffect, useState } from 'react';
import { ArrowUpCircle, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react';
import { fetchUpdates, updateAllSkills, updateSkill, type SkillUpdate } from '../../services/skillsMarketApi';

/** 更新列表是纯展示，方便测试与复用；数据获取放在默认导出的 UpdatesTab 里。 */
export function UpdatesList({ updates, busyName, updatingAll, onUpdate, onUpdateAll, onRefresh, loading, error }: {
  updates: SkillUpdate[];
  busyName: string;
  updatingAll: boolean;
  onUpdate: (name: string) => void;
  onUpdateAll: () => void;
  onRefresh: () => void;
  loading: boolean;
  error: string;
}) {
  return <section aria-label="技能更新">
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <span className="min-w-0 flex-1 text-[13px] text-fg-2">
        {loading ? '正在检查更新…' : updates.length ? `有 ${updates.length} 个技能可以更新。` : '所有技能都是最新的，暂时没有要更新的。'}
      </span>
      {updates.length > 1 && <button type="button" className="btn primary" disabled={updatingAll || loading} onClick={onUpdateAll}>
        {updatingAll ? <LoaderCircle size={15} className="spin" /> : <ArrowUpCircle size={15} />}{updatingAll ? '正在全部更新…' : '全部更新'}
      </button>}
      <button type="button" className="btn ghost" disabled={loading} onClick={onRefresh}><RefreshCw size={15} />重新检查</button>
    </div>
    {error && <div role="alert" className="error-note"><span>{error}</span><button type="button" className="btn ghost" onClick={onRefresh}>重试</button></div>}
    {loading && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3">正在向技能市场询问每个技能的最新版本…</div>}
    {!loading && !updates.length && !error && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3" role="status">
      一切正常。等你安装的技能发布了新版本，这里会列出来，你可以逐个更新，也可以一键全部更新。
    </div>}
    {!loading && updates.map((item) => <article key={`${item.source}:${item.name}`} className="card-surface mb-2 rounded-xl p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-fg">{item.name}</span>
        <span className="text-[12px] tabular-nums text-fg-3">{item.current_version} → <b className="font-medium text-fg">{item.latest_version}</b></span>
        <button type="button" className="btn primary h-7 px-2.5 text-[12px]" disabled={Boolean(busyName) || updatingAll} onClick={() => onUpdate(item.name)}>
          {busyName === item.name ? <LoaderCircle size={13} className="spin" /> : <ArrowUpCircle size={13} />}{busyName === item.name ? '更新中…' : '更新'}
        </button>
      </div>
      <p className="m-0 mt-1 text-[12px] text-fg-3">来源 {item.source}</p>
      {item.changes && <p className="m-0 mt-1.5 line-clamp-3 text-[12.5px] leading-relaxed text-fg-2"><Sparkles size={12} className="mr-1 inline text-brand" />{item.changes}</p>}
    </article>)}
  </section>;
}

/** 「更新」标签页：自查 GET /api/skills/updates，逐个或一键更新，失败给中文提示并可重试。 */
export default function UpdatesTab({ apiBaseUrl, onDone }: {
  apiBaseUrl: string;
  onDone?: (message: string) => void;
}) {
  const [updates, setUpdates] = useState<SkillUpdate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busyName, setBusyName] = useState('');
  const [updatingAll, setUpdatingAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setUpdates(await fetchUpdates(apiBaseUrl));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂时查不到更新，请稍后重试。');
      setUpdates([]);
    } finally { setLoading(false); }
  }, [apiBaseUrl]);

  useEffect(() => { void load(); }, [load]);

  const updateOne = async (name: string) => {
    setBusyName(name);
    setError('');
    try {
      await updateSkill(apiBaseUrl, name);
      onDone?.(`${name} 已更新到最新版本`);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `${name} 更新失败，请稍后再试。`);
    } finally { setBusyName(''); }
  };

  const updateEverything = async () => {
    setUpdatingAll(true);
    setError('');
    try {
      await updateAllSkills(apiBaseUrl);
      onDone?.('全部更新完成');
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '全部更新没有完成，请稍后再试。');
    } finally { setUpdatingAll(false); }
  };

  return <UpdatesList updates={updates} busyName={busyName} updatingAll={updatingAll}
    onUpdate={(name) => void updateOne(name)} onUpdateAll={() => void updateEverything()}
    onRefresh={() => void load()} loading={loading} error={error} />;
}
