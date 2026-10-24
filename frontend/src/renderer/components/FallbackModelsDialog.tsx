import { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, X } from 'lucide-react';
import { api } from '../services/api';

interface FallbackPayload { models: string[]; chain: string[] }

export default function FallbackModelsDialog({ apiBaseUrl, currentModel, onClose, onToast }: {
  apiBaseUrl: string; currentModel: string; onClose: () => void; onToast: (message: string) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [chain, setChain] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let stale = false;
    void api<FallbackPayload>(apiBaseUrl, '/api/models/fallback').then((result) => {
      if (!stale) { setModels(result.models); setChain(result.chain); }
    }).catch((cause) => { if (!stale) setError(cause instanceof Error ? cause.message : String(cause)); });
    return () => { stale = true; };
  }, [apiBaseUrl]);
  const toggle = (id: string) => setChain((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);
  const move = (index: number, offset: number) => setChain((items) => {
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= items.length) return items;
    const next = [...items]; [next[index], next[nextIndex]] = [next[nextIndex], next[index]]; return next;
  });
  const save = async () => {
    setSaving(true); setError('');
    try { await api(apiBaseUrl, '/api/models/fallback', { method: 'PUT', json: { chain } }); onToast('备用模型链已保存'); onClose(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setSaving(false); }
  };
  return <div className="fixed inset-0 z-[100] grid place-items-center bg-black/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label="备用模型链" className="w-full max-w-lg rounded-2xl border border-edge bg-panel p-5 shadow-2xl">
      <header className="flex items-center justify-between"><div><h2 className="m-0 text-[16px] font-semibold text-heading">备用模型链</h2><p className="mb-0 mt-1 text-[12px] text-fg-3">当前主模型：{currentModel || '自动选择'}。失败时按顺序尝试。</p></div><button className="rounded p-1 text-fg-3 hover:bg-hover" aria-label="关闭" onClick={onClose}><X size={16} /></button></header>
      <div className="mt-4 max-h-80 space-y-1 overflow-auto">{models.filter((id) => id !== currentModel).map((id) => {
        const index = chain.indexOf(id);
        return <div key={id} className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-hover">
          <input type="checkbox" checked={index >= 0} onChange={() => toggle(id)} aria-label={`使用 ${id} 作为备用模型`} />
          <span className="min-w-0 flex-1 truncate text-[13px]">{id}</span>
          {index >= 0 && <><span className="text-[11px] text-fg-3">第 {index + 1} 顺位</span><button aria-label={`${id} 上移`} disabled={index === 0} onClick={() => move(index, -1)} className="rounded p-1 text-fg-3 hover:bg-sunken disabled:opacity-30"><ArrowUp size={14} /></button><button aria-label={`${id} 下移`} disabled={index === chain.length - 1} onClick={() => move(index, 1)} className="rounded p-1 text-fg-3 hover:bg-sunken disabled:opacity-30"><ArrowDown size={14} /></button></>}
        </div>;
      })}</div>
      {error && <p role="alert" className="text-[12px] text-danger">{error}</p>}
      <footer className="mt-4 flex justify-end gap-2"><button className="rounded-lg px-3 py-2 text-[12px] text-fg-2 hover:bg-hover" onClick={onClose}>取消</button><button className="rounded-lg bg-brand px-3 py-2 text-[12px] text-white disabled:opacity-50" disabled={saving} onClick={() => void save()}>{saving ? '保存中…' : '保存'}</button></footer>
    </section>
  </div>;
}
