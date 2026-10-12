/**
 * Package-source inventory inspired by Pi resource packages and the Cline Marketplace.
 * Pi references: https://github.com/badlogic/pi-mono/blob/e37cdc420669e48b4df4bbce0fb2617fc3c71328/packages/coding-agent/docs/packages.md
 * https://github.com/badlogic/pi-mono/blob/e37cdc420669e48b4df4bbce0fb2617fc3c71328/packages/coding-agent/docs/extensions.md
 * Cline catalog reference: https://github.com/cline/marketplace
 */
import { useEffect, useState, type FormEvent } from 'react';
import { Check, CircleAlert, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

export type PackageResourceKind = 'extension' | 'skill' | 'prompt' | 'theme';
export type ExtensionPackageSource = {
  id: string;
  name: string;
  scope: 'user' | 'workspace' | 'project';
  source_type: 'local' | 'registry';
  source: string;
  resource_kinds: PackageResourceKind[];
  registry_metadata: Record<string, unknown>;
  validation_state: 'unvalidated' | 'valid' | 'unsupported' | 'invalid';
  diagnostics: string[];
};
type ScopeCapability = { available: boolean; reason: string };
type Draft = ExtensionPackageSource & { metadataText: string };
const kinds: { id: PackageResourceKind; label: string }[] = [
  { id: 'extension', label: '扩展' }, { id: 'skill', label: '技能' }, { id: 'prompt', label: '提示词' }, { id: 'theme', label: '主题' },
];
const blank = (): Draft => ({ id: globalThis.crypto?.randomUUID?.() ?? `source-${Date.now()}`, name: '', scope: 'user', source_type: 'local', source: '', resource_kinds: ['extension'], registry_metadata: {}, validation_state: 'unvalidated', diagnostics: [], metadataText: '{}' });
const toDraft = (source: ExtensionPackageSource): Draft => ({ ...source, metadataText: JSON.stringify(source.registry_metadata ?? {}, null, 2) });

/** Adds and validates source metadata. It never reads local files or downloads package code. */
export default function ExtensionPackagesPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [sources, setSources] = useState<ExtensionPackageSource[]>([]);
  const [scopeCapabilities, setScopeCapabilities] = useState<{ user: ScopeCapability; workspace: ScopeCapability; project: ScopeCapability }>({
    user: { available: true, reason: '用户级技能来源通过 Atlas Skill Market 加载。' },
    workspace: { available: false, reason: '正在读取后端作用范围能力。' },
    project: { available: false, reason: '正在读取后端作用范围能力。' },
  });
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const area = cn(field, 'h-auto py-2 font-mono text-[12px] leading-[1.55]');
  const fail = (error: unknown) => setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) });

  const load = async () => {
    const result = await api<{
      sources: ExtensionPackageSource[];
      execution_supported: boolean;
      scope_capabilities?: { user?: ScopeCapability; workspace?: ScopeCapability; project?: ScopeCapability };
    }>(apiBaseUrl, '/api/extension-packages');
    setSources(result.sources ?? []);
    setScopeCapabilities({
      user: result.scope_capabilities?.user ?? { available: false, reason: '后端没有声明用户级来源能力。' },
      workspace: result.scope_capabilities?.workspace ?? { available: false, reason: '后端没有声明工作区级来源能力。' },
      project: result.scope_capabilities?.project ?? { available: false, reason: '后端没有声明项目级来源能力。' },
    });
    if (!selectedId && result.sources?.length) setSelectedId(result.sources[0].id);
  };
  useEffect(() => {
    void load().catch((error) => {
      setScopeCapabilities({
        user: { available: false, reason: '无法读取后端作用范围能力。' },
        workspace: { available: false, reason: '无法读取后端作用范围能力；工作区来源已禁用。' },
        project: { available: false, reason: '无法读取后端作用范围能力；项目来源已禁用。' },
      });
      fail(error);
    });
  }, [apiBaseUrl]);
  useEffect(() => {
    if (isNew) return;
    const source = sources.find((item) => item.id === selectedId);
    setDraft(source ? toDraft(source) : null);
    setDeleteArmed(false);
  }, [sources, selectedId, isNew]);

  const update = (patch: Partial<Draft>) => setDraft((current) => current ? { ...current, ...patch } : current);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    let registryMetadata: Record<string, unknown>;
    try {
      registryMetadata = JSON.parse(draft.metadataText || '{}') as Record<string, unknown>;
      if (!registryMetadata || Array.isArray(registryMetadata) || typeof registryMetadata !== 'object') throw new Error('Registry metadata must be a JSON object.');
    } catch (error) { fail(error); return; }
    const payload: ExtensionPackageSource = {
      id: draft.id, name: draft.name.trim(), scope: draft.scope, source_type: draft.source_type, source: draft.source.trim(),
      resource_kinds: draft.resource_kinds, registry_metadata: registryMetadata, validation_state: 'unvalidated', diagnostics: [],
    };
    if (!payload.name || !payload.source || !payload.resource_kinds.length) { setMessage({ ok: false, text: '请填写名称、来源，并至少选择一种资源类型。' }); return; }
    if (payload.scope === 'workspace' && !scopeCapabilities.workspace.available) {
      setMessage({ ok: false, text: scopeCapabilities.workspace.reason || '当前后端不支持工作区级来源。' });
      return;
    }
    if (payload.scope === 'project' && !scopeCapabilities.project.available) {
      setMessage({ ok: false, text: scopeCapabilities.project.reason || '当前后端不支持项目级来源。' });
      return;
    }
    setBusy(true);
    try {
      const saved = await api<ExtensionPackageSource>(apiBaseUrl, isNew ? '/api/extension-packages' : `/api/extension-packages/${encodeURIComponent(payload.id)}`, { method: isNew ? 'POST' : 'PUT', json: payload });
      setSources((current) => isNew ? [...current, saved] : current.map((item) => item.id === saved.id ? saved : item));
      setSelectedId(saved.id); setIsNew(false); setMessage({ ok: true, text: '来源信息已保存。可以进行只读声明检查。' });
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  };
  const validate = async () => {
    if (!draft || isNew) return;
    setBusy(true);
    try {
      const result = await api<ExtensionPackageSource>(apiBaseUrl, `/api/extension-packages/${encodeURIComponent(draft.id)}/validate`, { method: 'POST' });
      setSources((current) => current.map((item) => item.id === result.id ? result : item));
      setDraft(toDraft(result));
      setMessage({ ok: result.validation_state === 'valid', text: result.validation_state === 'valid' ? '登记信息的 URL 格式有效。' : '检查完成；请查看诊断。' });
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!draft || isNew) return;
    if (!deleteArmed) { setDeleteArmed(true); return; }
    setBusy(true);
    try {
      await api(apiBaseUrl, `/api/extension-packages/${encodeURIComponent(draft.id)}`, { method: 'DELETE' });
      const remaining = sources.filter((item) => item.id !== draft.id);
      setSources(remaining); setSelectedId(remaining[0]?.id ?? ''); setDraft(remaining[0] ? toDraft(remaining[0]) : null); setMessage({ ok: true, text: '来源已移除。' });
    } catch (error) { fail(error); }
    finally { setBusy(false); setDeleteArmed(false); }
  };

  return <section className="grid gap-4" aria-label="扩展包来源">
    <header><h2 className="text-[15px] font-semibold text-fg">扩展包来源</h2><p className="mt-1 text-[12.5px] text-fg-3">用户级技能来源可连接到 Atlas Skill Market。扩展代码、提示词和主题目前只登记为元数据，不会安装或执行；本地技能目录检查只读取目录结构，注册表检查不会抓取远端内容。</p></header>
    <div className="rounded-xl bg-sunken px-3 py-2 text-[12px] text-fg-2" role="status">
      <span className="font-medium">工作区范围：{scopeCapabilities.workspace.available ? '可用' : '不可用'} · 项目范围：{scopeCapabilities.project.available ? '可用' : '不可用'}</span>
      <p className="mt-1 text-fg-3">{scopeCapabilities.workspace.reason || '后端未提供工作区级来源能力。'} {scopeCapabilities.project.reason || '后端未提供项目级来源能力。'}</p>
      {!scopeCapabilities.workspace.available && !scopeCapabilities.project.available && <p className="mt-1 text-fg-3">当前设置 API 未收到活动 workspace，也没有按工作区/项目隔离的加载器；这些范围不会被保存为有效覆盖。</p>}
    </div>
    <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-5">
      <nav className="grid content-start gap-1" aria-label="包来源列表">
        {sources.map((source) => <button key={source.id} onClick={() => { setSelectedId(source.id); setIsNew(false); setMessage(null); }} aria-current={!isNew && source.id === selectedId}
          className={cn('rounded-lg px-2.5 py-2 text-left text-[13px]', !isNew && source.id === selectedId ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover')}>
          <span className="block truncate font-medium">{source.name}</span><span className="mt-0.5 block truncate text-[11px] text-fg-3">{source.scope} · {source.source_type} · {source.validation_state}</span>
        </button>)}
        <Button variant="ghost" size="sm" className="justify-start" onClick={() => { setDraft(blank()); setSelectedId(''); setIsNew(true); setMessage(null); }}><Plus />添加来源</Button>
        {!sources.length && !isNew && <p className="px-2 py-3 text-[12px] text-fg-3">尚未登记包来源。</p>}
      </nav>

      {draft ? <form onSubmit={(event) => void save(event)} className="grid content-start gap-3 text-[12.5px] text-fg-2">
        <div className="grid grid-cols-2 gap-3"><label className="grid gap-1">显示名称<input required value={draft.name} onChange={(event) => update({ name: event.target.value })} className={field} /></label><label className="grid gap-1">作用范围<select value={draft.scope} onChange={(event) => update({ scope: event.target.value as Draft['scope'] })} className={field}><option value="user" disabled={!scopeCapabilities.user.available}>用户</option><option value="workspace" disabled={!scopeCapabilities.workspace.available}>工作区{scopeCapabilities.workspace.available ? '' : '（不可用）'}</option><option value="project" disabled={!scopeCapabilities.project.available}>项目{scopeCapabilities.project.available ? '' : '（不可用）'}</option></select></label></div>
        <div className="grid grid-cols-2 gap-3"><label className="grid gap-1">来源类型<select value={draft.source_type} onChange={(event) => update({ source_type: event.target.value as Draft['source_type'], validation_state: 'unvalidated', diagnostics: [] })} className={field}><option value="local">本地路径</option><option value="registry">注册表 URL</option></select></label><label className="grid gap-1">{draft.source_type === 'local' ? '本地路径（仅登记）' : '注册表 URL'}<input required value={draft.source} onChange={(event) => update({ source: event.target.value })} className={cn(field, 'font-mono text-[12px]')} placeholder={draft.source_type === 'local' ? 'D:\\packages\\my-extension' : 'https://example.com/catalog.json'} /></label></div>
        <fieldset className="grid gap-2"><legend>资源类型</legend><div className="flex flex-wrap gap-2">{kinds.map((kind) => <label key={kind.id} className="flex items-center gap-1.5 rounded-lg bg-sunken px-2.5 py-1.5 shadow-[inset_0_0_0_1px_var(--line)]"><input type="checkbox" checked={draft.resource_kinds.includes(kind.id)} onChange={(event) => update({ resource_kinds: event.target.checked ? [...draft.resource_kinds, kind.id] : draft.resource_kinds.filter((value) => value !== kind.id) })} />{kind.label}</label>)}</div></fieldset>
        <label className="grid gap-1">注册表元数据（JSON 对象）<small className="text-fg-3">可填写 registry、publisher、version、repository、catalog_url 等字段。</small><textarea rows={7} value={draft.metadataText} onChange={(event) => update({ metadataText: event.target.value })} className={area} /></label>
        <div className="flex flex-wrap gap-2"><Button type="submit" variant="primary" disabled={busy}><Save />{busy ? '处理中…' : '保存来源'}</Button>{!isNew && <Button disabled={busy} onClick={() => void validate()}><RefreshCw />只读检查</Button>}{!isNew && <Button variant="danger" disabled={busy} onClick={() => void remove()}><Trash2 />{deleteArmed ? '再次点击确认移除' : '移除'}</Button>}</div>
        {!isNew && <div className={cn('grid gap-1 rounded-xl p-3 text-[12px]', draft.validation_state === 'invalid' ? 'bg-danger-soft text-danger' : draft.validation_state === 'valid' ? 'bg-selected text-brand' : 'bg-sunken text-fg-2')} role="status"><div className="flex items-center gap-2 font-medium">{draft.validation_state === 'invalid' ? <CircleAlert size={14} /> : <Check size={14} />}{draft.validation_state}</div>{draft.diagnostics.map((line, index) => <p key={index}>{line}</p>)}</div>}
      </form> : <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-line text-[13px] text-fg-3">选择一个来源，或添加来源。</div>}
    </div>
    {message && <p role="status" className={cn('whitespace-pre-wrap text-[12px]', message.ok ? 'text-brand' : 'text-danger')}>{message.text}</p>}
  </section>;
}
