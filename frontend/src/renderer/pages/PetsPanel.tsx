import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';

type Pet = { id: string; name: string; description: string; emoji: string; color: string; avatar?: string | null; avatar_url?: string; builtin: boolean; version: string };
type Catalog = { pets: Pet[]; active_id: string };

export default function PetsPanel({ apiBaseUrl, onToast, hatchOnOpen = false }: { apiBaseUrl: string; onToast: (message: string) => void; hatchOnOpen?: boolean }) {
  const [catalog, setCatalog] = useState<Catalog>({ pets: [], active_id: 'atlas-companion' });
  const [name, setName] = useState('');
  const [emoji, setEmoji] = useState('🐾');
  const [color, setColor] = useState('#8277f4');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async () => setCatalog(await api<Catalog>(apiBaseUrl, '/api/pets')), [apiBaseUrl]);
  useEffect(() => { void refresh().catch((error) => onToast(`读取宠物目录失败：${String(error)}`)); }, [refresh, onToast]);
  const run = async (operation: () => Promise<Catalog | { pets: Pet[]; active_id: string; pet: Pet }>, success: string) => {
    setBusy(true);
    try { const result = await operation(); setCatalog(result); onToast(success); }
    catch (error) { onToast(`宠物操作失败：${error instanceof Error ? error.message : String(error)}`); }
    finally { setBusy(false); }
  };
  const hatch = () => {
    if (!name.trim()) { onToast('先给新宠物起个名字'); return; }
    void run(() => api(apiBaseUrl, '/api/pets/hatch', { method: 'POST', json: { name, emoji, color } }), `「${name.trim()}」孵化完成并已启用`);
    setName('');
  };
  const install = async (file?: File) => {
    if (!file) return;
    const body = new FormData(); body.append('file', file);
    await run(() => api(apiBaseUrl, '/api/pets/install', { method: 'POST', body }), `已安装宠物包「${file.name}」`);
    if (fileRef.current) fileRef.current.value = '';
  };
  return <div className="grid max-w-4xl gap-6" data-testid="pets-panel">
    <section className="rounded-2xl border border-line bg-surface p-4">
      <h4 className="m-0 text-[14px] font-semibold">桌宠 overlay</h4>
      <p className="mt-1 text-[12px] text-fg-3">桌宠跟随 Atlas 的空闲、运行和等待状态变化。桌面端支持常驻置顶的浮动窗口。</p>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => window.atlasDesktop?.togglePetOverlay?.()} className="rounded-lg bg-brand px-3 py-2 text-[12px] text-white">打开 / 隐藏桌宠</button>
        <span className="text-[11px] text-fg-3">键盘命令：/pet 打开或隐藏，/hatch 在此孵化新宠物。</span>
      </div>
    </section>
    <section className="rounded-2xl border border-line bg-surface p-4">
      <h4 className="m-0 text-[14px] font-semibold">本地宠物市场</h4>
      <p className="mt-1 text-[12px] text-fg-3">目录只管理本机宠物包，不依赖云账号。ZIP 根目录须包含 manifest.json（id、name、emoji、color、avatar 可选）。</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {catalog.pets.map((pet) => <article key={pet.id} data-pet-id={pet.id} className={`flex min-w-0 items-center gap-3 rounded-xl border p-3 ${catalog.active_id === pet.id ? 'border-brand bg-brand/5' : 'border-line'}`}>
          {pet.avatar_url ? <img src={`${apiBaseUrl}${pet.avatar_url}`} alt="" className="h-12 w-12 rounded-xl object-cover" /> : <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl text-2xl" style={{ backgroundColor: `${pet.color}25` }}>{pet.emoji}</span>}
          <div className="min-w-0 flex-1"><strong className="block truncate text-[13px]">{pet.name}{catalog.active_id === pet.id && <span className="ml-1 text-[10px] text-brand">使用中</span>}</strong><p className="m-0 truncate text-[11px] text-fg-3">{pet.description || '本地宠物包'}{pet.builtin ? ' · 内置' : ` · v${pet.version}`}</p></div>
          {catalog.active_id !== pet.id && <button disabled={busy} type="button" onClick={() => void run(() => api(apiBaseUrl, `/api/pets/${encodeURIComponent(pet.id)}/active`, { method: 'PUT' }), `已切换到「${pet.name}」`)} className="rounded-lg border border-line px-2.5 py-1.5 text-[11px] disabled:opacity-50">切换</button>}
          {!pet.builtin && <button disabled={busy} type="button" aria-label={`移除${pet.name}`} onClick={() => { if (window.confirm(`从本机移除宠物「${pet.name}」？`)) void run(() => api(apiBaseUrl, `/api/pets/${encodeURIComponent(pet.id)}`, { method: 'DELETE' }), `已移除「${pet.name}」`); }} className="rounded-lg px-2 py-1.5 text-[11px] text-danger hover:bg-hover disabled:opacity-50">移除</button>}
        </article>)}
      </div>
      <div className="mt-4 flex flex-wrap gap-2"><input ref={fileRef} type="file" accept=".zip,application/zip" className="hidden" onChange={(event) => void install(event.target.files?.[0])} /><button disabled={busy} type="button" onClick={() => fileRef.current?.click()} className="rounded-lg border border-line px-3 py-2 text-[12px] disabled:opacity-50">导入 / 安装 ZIP 宠物包</button><button type="button" onClick={() => void refresh()} className="rounded-lg px-3 py-2 text-[12px] text-fg-2 hover:bg-hover">刷新目录</button></div>
    </section>
    <section className="rounded-2xl border border-line bg-surface p-4">
      <h4 className="m-0 text-[14px] font-semibold">孵化新宠物</h4>
      <p className="mt-1 text-[12px] text-fg-3">生成一个保存在本机数据目录中的轻量宠物包，孵化后自动启用。</p>
      <div className="mt-3 flex flex-wrap items-end gap-3"><label className="grid gap-1 text-[11px] text-fg-2">名字<input autoFocus={hatchOnOpen} value={name} onChange={(event) => setName(event.target.value)} maxLength={80} placeholder="例如：小云" className="h-9 w-48 rounded-lg border border-line bg-surface px-2.5 text-[12px]" /></label><label className="grid gap-1 text-[11px] text-fg-2">表情<input value={emoji} onChange={(event) => setEmoji(event.target.value)} maxLength={8} className="h-9 w-20 rounded-lg border border-line bg-surface px-2.5 text-center text-[18px]" /></label><label className="grid gap-1 text-[11px] text-fg-2">主题色<input type="color" value={color} onChange={(event) => setColor(event.target.value)} className="h-9 w-16 rounded-lg border border-line bg-surface p-1" /></label><button disabled={busy || !name.trim()} type="button" onClick={hatch} className="rounded-lg bg-brand px-4 py-2 text-[12px] text-white disabled:opacity-50">孵化并启用</button></div>
    </section>
  </div>;
}
