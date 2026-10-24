import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';

type Category = { id: string; label: string; bytes: number; can_clear: boolean };
type Retention = { days: number; action: 'archive' | 'delete'; exclude_pinned: boolean; exclude_projects: boolean };
const bytesLabel = (bytes: number) => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export default function StorageRetentionPanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (message: string) => void }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [retention, setRetention] = useState<Retention>({ days: 0, action: 'archive', exclude_pinned: true, exclude_projects: true });
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    try { const [storage, policy] = await Promise.all([api<{ categories: Category[] }>(apiBaseUrl, '/api/u6/storage'), api<Retention>(apiBaseUrl, '/api/u6/retention')]); setCategories(storage.categories); setRetention(policy); setError(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [apiBaseUrl]);
  useEffect(() => { void refresh(); }, [refresh]);
  const clear = async (category: Category) => {
    const warning = category.id === 'sessions' ? '这会永久删除全部会话和消息。' : '';
    if (!category.can_clear || !window.confirm(`${warning}清理${category.label}，预计释放 ${bytesLabel(category.bytes)}？`)) return;
    try { const result = await api<{ released_bytes: number }>(apiBaseUrl, `/api/u6/storage/${category.id}`, { method: 'DELETE', json: { confirm: true } }); onToast(`已清理${category.label}，释放 ${bytesLabel(result.released_bytes)}`); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const save = async () => {
    try { const saved = await api<Retention>(apiBaseUrl, '/api/u6/retention', { method: 'PUT', json: retention }); setRetention(saved); await api(apiBaseUrl, '/api/u6/retention/run'); onToast('会话保留期限已保存；符合规则的旧会话已处理'); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  return <div className="grid max-w-[760px] gap-6">
    <section className="grid gap-3 rounded-xl border border-line p-4">
      <div><h4 className="m-0 text-[13.5px] font-medium text-heading">存储占用</h4><p className="mt-1 mb-0 text-[11.5px] text-fg-3">清理前会显示预计可释放空间；清理会话数据库会删除全部会话和消息。</p></div>
      {categories.map((item) => <div key={item.id} className="flex items-center gap-3 border-t border-line pt-2.5 text-[12px]"><span className="flex-1">{item.label}</span><span className="text-fg-3">{bytesLabel(item.bytes)}</span><button disabled={!item.can_clear || item.bytes === 0} onClick={() => void clear(item)} className="rounded-md border border-line px-2.5 py-1 text-[11px] disabled:opacity-40">清理</button></div>)}
      <button onClick={() => void refresh()} className="justify-self-start rounded-md px-2 py-1 text-[11px] text-fg-3 hover:bg-hover">刷新占用</button>
    </section>
    <section className="grid gap-3 rounded-xl border border-line p-4">
      <div><h4 className="m-0 text-[13.5px] font-medium text-heading">会话保留期限</h4><p className="mt-1 mb-0 text-[11.5px] text-fg-3">0 表示永久保留；过期会话每日自动处理。</p></div>
      <label className="grid max-w-[300px] gap-1 text-[12px]">保留天数<input type="number" min={0} max={36500} value={retention.days} onChange={(event) => setRetention({ ...retention, days: Math.max(0, Number(event.target.value) || 0) })} className="h-9 rounded-lg border border-line bg-surface px-2" /></label>
      <label className="grid max-w-[300px] gap-1 text-[12px]">到期操作<select value={retention.action} onChange={(event) => setRetention({ ...retention, action: event.target.value as Retention['action'] })} className="h-9 rounded-lg border border-line bg-surface px-2"><option value="archive">归档</option><option value="delete">删除</option></select></label>
      <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={retention.exclude_pinned} onChange={(event) => setRetention({ ...retention, exclude_pinned: event.target.checked })} />排除置顶会话</label>
      <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={retention.exclude_projects} onChange={(event) => setRetention({ ...retention, exclude_projects: event.target.checked })} />排除项目内会话</label>
      <button onClick={() => void save()} className="justify-self-start rounded-lg bg-brand px-3 py-1.5 text-[12px] text-on-primary">保存保留规则</button>
    </section>
    {error && <p role="alert" className="m-0 text-[12px] text-danger">{error}</p>}
  </div>;
}
