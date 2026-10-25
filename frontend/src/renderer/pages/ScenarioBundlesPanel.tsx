import { useEffect, useState } from 'react';

type Bundle = { name: string; description: string; skills: string[]; memory_collections: string[]; tools: string[] };
type Snapshot = { bundles: Bundle[]; loaded: { name: string; memory_collections: string[]; tools: string[] } | null };
const empty: Bundle = { name: '', description: '', skills: [], memory_collections: [], tools: [] };

async function request<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}/api/scenario-bundles${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) { const body = await response.json().catch(() => ({})) as { detail?: string }; throw new Error(body.detail || `请求失败（${response.status}）`); }
  return response.json() as Promise<T>;
}
const split = (value: string) => value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);

export default function ScenarioBundlesPanel({ apiBaseUrl, onToast, onApplySkills, onRemoveSkills }: {
  apiBaseUrl: string; onToast: (message: string) => void; onApplySkills: (names: string[]) => void; onRemoveSkills: (names: string[]) => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot>({ bundles: [], loaded: null });
  const [form, setForm] = useState<Bundle>(empty);
  const [skillText, setSkillText] = useState(''); const [memoryText, setMemoryText] = useState(''); const [toolText, setToolText] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ name: string; active_skills: string[]; memory_collections: string[]; tools: string[]; conflicts: Array<{ type: string; name: string }> } | null>(null);
  const refresh = async () => setSnapshot(await request<Snapshot>(apiBaseUrl, ''));
  useEffect(() => { void refresh().catch((cause: Error) => onToast(cause.message)); }, [apiBaseUrl]);
  const edit = (item: Bundle) => { setForm(item); setSkillText(item.skills.join(', ')); setMemoryText(item.memory_collections.join(', ')); setToolText(item.tools.join(', ')); };
  const save = async () => {
    setBusy(true);
    try { await request(apiBaseUrl, '', { method: 'POST', body: JSON.stringify({ ...form, skills: split(skillText), memory_collections: split(memoryText), tools: split(toolText) }) }); await refresh(); onToast(`已保存场景包「${form.name}」`); }
    catch (cause) { onToast((cause as Error).message); } finally { setBusy(false); }
  };
  const load = async (name: string) => {
    setBusy(true);
    try {
      const result = await request<Omit<NonNullable<typeof preview>, 'name'>>(apiBaseUrl, `/${encodeURIComponent(name)}/preview`);
      setPreview({ ...result, name });
    } catch (cause) { onToast((cause as Error).message); } finally { setBusy(false); }
  };
  const confirmLoad = async () => {
    if (!preview || preview.conflicts.length) return;
    setBusy(true);
    try {
      const result = await request<{ active_skills: string[] }>(apiBaseUrl, `/${encodeURIComponent(preview.name)}/load`, { method: 'POST' });
      onApplySkills(result.active_skills); await refresh(); onToast(`已加载「${preview.name}」；技能会用于后续对话，记忆集合与工具配置已切换`); setPreview(null);
    } catch (cause) { onToast((cause as Error).message); } finally { setBusy(false); }
  };
  const unload = async () => {
    setBusy(true);
    try { const previous = snapshot.loaded; await request(apiBaseUrl, '/unload', { method: 'POST' }); if (previous) onRemoveSkills(snapshot.bundles.find((item) => item.name === previous.name)?.skills ?? []); await refresh(); onToast('已卸载当前场景包'); }
    catch (cause) { onToast((cause as Error).message); } finally { setBusy(false); }
  };
  const remove = async (name: string) => {
    try { await request(apiBaseUrl, `/${encodeURIComponent(name)}`, { method: 'DELETE' }); await refresh(); }
    catch (cause) { onToast((cause as Error).message); }
  };

  return <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.9fr)]">
    {preview && <div role="dialog" aria-modal="true" aria-label="加载场景包预览" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"><section className="grid max-h-[80vh] w-full max-w-xl gap-3 overflow-auto rounded-xl card-surface p-5"><h2 className="m-0 text-[16px]">加载前检查：{preview.name}</h2><p className="m-0 text-[13px]">技能：{preview.active_skills.join('、') || '无'}<br />记忆集合：{preview.memory_collections.join('、') || '无'}<br />可选工具配置：{preview.tools.join('、') || '默认'}</p><div><strong>冲突检查</strong>{preview.conflicts.length ? <ul role="alert">{preview.conflicts.map((item) => <li key={`${item.type}:${item.name}`}>{item.type}：{item.name}</li>)}</ul> : <p role="status">没有发现缺失技能或记忆集合冲突。</p>}</div><div className="flex justify-end gap-2"><button onClick={() => setPreview(null)}>取消</button><button disabled={busy || !!preview.conflicts.length} onClick={() => void confirmLoad()}>确认加载</button></div></section></div>}
    <section className="grid content-start gap-3 rounded-xl card-surface p-4" aria-label="场景包列表">
      <div className="flex items-center gap-2"><h2 className="m-0 flex-1 text-[15px] font-semibold">技能组与场景记忆包</h2>{snapshot.loaded && <button disabled={busy} onClick={() => void unload()}>卸载当前包</button>}</div>
      <p className="m-0 text-[12px] text-fg-3">按场景组合已安装技能、记忆集合和可选工具配置。加载前会核对技能和记忆集合；技能用于后续 Agent 对话。</p>
      {snapshot.loaded && <div role="status" className="rounded-lg bg-sunken p-3 text-[13px]">当前：<strong>{snapshot.loaded.name}</strong><div>记忆集合：{snapshot.loaded.memory_collections.join('、') || '无'} · 工具：{snapshot.loaded.tools.join('、') || '默认'}</div></div>}
      {!snapshot.bundles.length && <p className="text-[13px] text-fg-3">还没有场景包。右侧创建一个，或使用 `atlas bundle save manifest.json` 导入。</p>}
      {snapshot.bundles.map((item) => <article key={item.name} className="grid gap-2 rounded-lg border border-[var(--line)] p-3">
        <div className="flex items-center gap-2"><strong className="flex-1">{item.name}</strong><button disabled={busy} onClick={() => void load(item.name)}>{snapshot.loaded?.name === item.name ? '重新加载' : '加载'}</button><button onClick={() => edit(item)}>编辑</button><button onClick={() => void remove(item.name)}>删除</button></div>
        <p className="m-0 text-[12px] text-fg-3">{item.description || '无描述'}</p><small>技能：{item.skills.join('、') || '无'} · 记忆集合：{item.memory_collections.join('、') || '无'} · 工具配置：{item.tools.join('、') || '默认'}</small>
      </article>)}
    </section>
    <section className="grid content-start gap-3 rounded-xl card-surface p-4" aria-label="编辑场景包">
      <h2 className="m-0 text-[15px] font-semibold">{snapshot.bundles.some((item) => item.name === form.name) ? '编辑场景包' : '新建场景包'}</h2>
      <label className="grid gap-1 text-[12px]">名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="rounded-lg bg-sunken p-2 text-fg" maxLength={80} /></label>
      <label className="grid gap-1 text-[12px]">描述<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} className="rounded-lg bg-sunken p-2 text-fg" /></label>
      <label className="grid gap-1 text-[12px]">技能名称（逗号分隔）<textarea value={skillText} onChange={(event) => setSkillText(event.target.value)} className="min-h-16 rounded-lg bg-sunken p-2 text-fg" placeholder="research, python" /></label>
      <label className="grid gap-1 text-[12px]">记忆集合（记忆库中的集合/路径）<textarea value={memoryText} onChange={(event) => setMemoryText(event.target.value)} className="min-h-16 rounded-lg bg-sunken p-2 text-fg" placeholder="项目/Atlas, 偏好" /></label>
      <label className="grid gap-1 text-[12px]">可选工具配置名称<textarea value={toolText} onChange={(event) => setToolText(event.target.value)} className="min-h-16 rounded-lg bg-sunken p-2 text-fg" placeholder="browser, terminal" /></label>
      <div className="flex gap-2"><button disabled={busy || !form.name.trim()} onClick={() => void save()}>保存场景包</button><button onClick={() => edit(empty)}>清空</button></div>
    </section>
  </div>;
}
